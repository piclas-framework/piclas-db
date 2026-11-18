# ==================================================================================================================================
# Copyright (c) 2026 Stephen Copplestone and the piclas-db contributors (see CONTRIBUTORS.md)
#
# This file is part of piclas-db (github.com/piclas-framework/piclas-db). piclas-db is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3
# of the License, or (at your option) any later version.
#
# piclas-db is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License v3.0 for more details.
#
# You should have received a copy of the GNU General Public License along with piclas-db. If not, see <https://www.gnu.org/licenses/>.
# ==================================================================================================================================
"""Fit formulas from papers (e.g. Janev et al. 2003): safe evaluation of an expression in the energy E

A formula is stored like a table extraction, with the expression, its parameters, the energy range in which the paper gives it,
the units and an optional threshold below which the cross-section is zero. Only arithmetic, powers, the functions exp, log, log10,
sqrt and abs, the variable E and the named parameters are allowed: an expression can never run code.

    formula:
      expression: 4.05 / E**0.653 * exp(-3.15 / (E - 2.0)**1.65) + 0.139 * E**0.318 * exp(-680 / E**2.10) / (1 + a * E**2.65 + b * E**4.65)
      parameters: {a: 2.75e-12, b: 9.04e-23}
      threshold: 2.0          # eV (in the energy unit of the record), cross-section zero below
      range: [2.0, 1.0e5]     # validity range given in the paper
      points: 200             # logarithmic grid over the range

Parameters can come from a stored parameter table (a table of the paper read with 'extract --table'), one column per formula:

    parameters_from:
      table: janev-2003/table3   # [@sha256]
      column: 1s                 # header text or number (1 = first value column)
      rows: {I: In (eV)}         # parameter name -> row label where they differ (compared without spaces and case)
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import ast
from typing import Any
from collections.abc import Callable

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import numpy as np
# ==================================================================================================================================

FUNCTIONS: dict[str, Callable[[np.ndarray], np.ndarray]] = {'exp': np.exp, 'log': np.log, 'log10': np.log10, 'sqrt': np.sqrt, 'abs': np.abs}
OPERATORS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: np.add,
    ast.Sub: np.subtract,
    ast.Mult: np.multiply,
    ast.Div: np.divide,
    ast.Pow: np.power,
}


class FormulaError(Exception):
    """Invalid formula"""


def compile_formula(expression: str, parameters: dict[str, float]) -> Callable[[np.ndarray], np.ndarray]:
    """Function of E (array) for an expression; raises FormulaError for anything but arithmetic on E, parameters and FUNCTIONS"""
    try:
        tree = ast.parse(expression.replace('^', '**'), mode='eval')
    except SyntaxError as e:
        raise FormulaError(f'cannot parse {expression!r}: {e.msg}') from e
    unknown = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} - {'E'} - set(parameters) - set(FUNCTIONS)
    if unknown:
        raise FormulaError(f'unknown names {", ".join(sorted(unknown))} (allowed: E, the parameters, {", ".join(FUNCTIONS)})')

    def evaluate(node: ast.AST, energy: np.ndarray) -> Any:
        if isinstance(node, ast.Expression):
            return evaluate(node.body, energy)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name):
            return energy if node.id == 'E' else float(parameters[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
            return OPERATORS[type(node.op)](evaluate(node.left, energy), evaluate(node.right, energy))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = evaluate(node.operand, energy)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS and len(node.args) == 1 and not node.keywords:
            return FUNCTIONS[node.func.id](evaluate(node.args[0], energy))
        raise FormulaError(f'not allowed in a formula: {ast.dump(node)[:60]}')

    with np.errstate(all='ignore'):
        evaluate(tree, np.array([1.0]))  # structure check (raises for forbidden constructs)

    def function(energy: np.ndarray) -> np.ndarray:
        with np.errstate(all='ignore'):
            return np.asarray(evaluate(tree, np.asarray(energy, dtype=np.float64)), dtype=np.float64) * np.ones_like(energy, dtype=np.float64)

    return function


def tabulate(formula: dict) -> tuple[np.ndarray, np.ndarray]:
    """Energies (log grid over the range, threshold included) and cross-sections in the units of the record; zero below threshold"""
    try:
        low, high = (float(value) for value in formula['range'])
        expression = str(formula['expression'])
    except (KeyError, TypeError, ValueError) as e:
        raise FormulaError('formula needs expression and range: [min, max]') from e
    if not 0.0 < low < high:
        raise FormulaError(f'range must be 0 < min < max, got {formula["range"]}')
    function = compile_formula(expression, {str(k): float(v) for k, v in (formula.get('parameters') or {}).items()})
    threshold = formula.get('threshold')
    energy = np.geomspace(low, high, int(formula.get('points', 200)))
    if threshold is not None:
        threshold = float(threshold)
        energy = np.unique(np.concatenate([[threshold], energy[energy > threshold]])) if threshold >= low else energy
    sigma = function(energy)
    if threshold is not None:
        sigma = np.where(energy <= threshold, 0.0, sigma)
    if not np.all(np.isfinite(sigma)):
        bad = energy[~np.isfinite(sigma)]
        raise FormulaError(f'formula not finite at {bad[0]:g} (and {len(bad) - 1} more energies): threshold or range missing?')
    if np.any(sigma < 0.0):
        raise FormulaError(f'formula negative at {energy[np.argmax(sigma < 0.0)]:g}')
    return energy, sigma
