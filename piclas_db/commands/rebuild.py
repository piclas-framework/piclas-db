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
# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import argparse
import copy
import pathlib
from collections import Counter

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db import provenance
from piclas_db.build import BuildError, build
from piclas_db.compare import compare
from piclas_db.git import GitError
from piclas_db.guide import guide
from piclas_db.model import CollisionPair, Database
from piclas_db.readers import DatabaseReadError, read_database
from piclas_db.rebuild import Derivation, derive, recipe_yaml
from piclas_db.recipe import RecipeError, parse_recipe
from piclas_db.resolve import Origin, resolve
from piclas_db.store import Store
from piclas_db.writer import write_database
# ==================================================================================================================================


def copy_not_rebuilt(old: Database, new: Database) -> list[str]:
    """Copy everything that was not rebuilt from original files, so that the new file is complete; returns what was copied"""
    copied = []
    for name, species in old.species.items():
        target = new.species.setdefault(name, copy.deepcopy(species))
        if target is species or target.attributes == {} and species.attributes:
            target.attributes = copy.deepcopy(species.attributes)
        if target.electronic_levels is None and (species.electronic_levels is not None or species.electronic_placeholder):
            target.electronic_levels, target.electronic_placeholder = copy.deepcopy(species.electronic_levels), species.electronic_placeholder
            copied.append(f'/Species/{name}/ElectronicLevel')
        if not target.provenance.reference and species.provenance.reference:
            target.provenance = copy.deepcopy(species.provenance)
    for name, pair in old.collision_pairs.items():
        target_pair = new.collision_pairs.setdefault(name, CollisionPair(name=name, provenance=copy.deepcopy(pair.provenance)))
        present = {(xsec.group, xsec.key) for xsec in target_pair.cross_sections}
        kinds = {xsec.kind for xsec in target_pair.cross_sections}
        for xsec in pair.cross_sections:
            if (xsec.group, xsec.key) not in present and not (xsec.group is None and xsec.kind in kinds):
                target_pair.cross_sections.append(copy.deepcopy(xsec))
                copied.append(f'/Cross-Sections/{name}/' + (f'{xsec.group}/' if xsec.group else '') + xsec.key)
    for attribute in ('reactions', 'surface'):
        getattr(new, attribute).update(copy.deepcopy(getattr(old, attribute)))
    new.diffusion = copy.deepcopy(old.diffusion)
    new.attributes = copy.deepcopy(old.attributes)
    if old.reactions:
        copied.append(f'{len(old.reactions)} reaction(s)')
    if old.diffusion or old.surface:
        copied.append('diffusion and surface data')
    return copied


def run(args: argparse.Namespace) -> int:
    """Rebuild an existing database from the original files and compare the result with the original"""
    output = pathlib.Path(args.output)
    recipe_file = pathlib.Path(args.recipe_out) if args.recipe_out else output.with_suffix('.recipe.yaml')
    if output.exists() and not args.force:
        print(f'ERROR: {output} exists (use --force to overwrite)')
        return 1
    store = Store(args.store)
    try:
        old = read_database(args.source)
        embedded = provenance.read(old.attributes)
        if embedded.recipe_intact and not args.derive:
            # Built by piclas-db: the embedded recipe (with the exact original files) is used instead of deriving one
            assert embedded.recipe is not None
            recipe_text = embedded.recipe
            derivation = Derivation(recipe=parse_recipe(recipe_text, f'embedded in {args.source}'))
            origin = f'Recipe embedded in {args.source} (piclas-db {embedded.version}, {embedded.created})'
        else:
            derivation = derive(old, store, levels_from_nist=args.levels_from_nist)
            recipe_text = yaml.safe_dump(recipe_yaml(derivation.recipe, derivation.unresolved), sort_keys=False, allow_unicode=True, width=1000)
            origin = f'Recipe derived from {args.source}'
        recipe_file.write_text(recipe_text)
        resolutions = resolve(store, derivation.recipe.requirements, update=not args.offline)
    except (DatabaseReadError, GitError, OSError, RecipeError) as e:
        print(f'ERROR: {e}')
        return 1

    print(f'{origin}: {recipe_file}')
    for resolution in resolutions:
        print(f'  {resolution.origin.value:20s} {resolution.requirement}' + (f': {resolution.entry.relative}' if resolution.entry else ''))
    missing = [resolution.requirement for resolution in resolutions if resolution.origin is Origin.MANUAL]
    if missing:
        print('\nOriginal files missing. Download them, import them and run rebuild again:\n')
        for requirement in missing:
            print('\n'.join(guide(requirement)))
            print()
        print(f'piclas-db import --source-dir ~/Downloads && piclas-db rebuild {args.source} -o {output}')
        return 1
    if not derivation.recipe.requirements:
        print('Nothing in the file can be rebuilt from original files (no usable provenance):')
        for line in derivation.unresolved:
            print(f'  {line}')
        return 1

    try:
        new, report = build(derivation.recipe, resolutions)
    except BuildError as e:
        print(f'ERROR: {e}')
        return 1
    copied = copy_not_rebuilt(old, new)
    sources = [(str(resolution.requirement), resolution.entry.relative, str(resolution.entry.meta.get('sha256')), resolution.entry.meta.get('retrieved')) for resolution in resolutions if resolution.entry is not None]
    record = provenance.create(f'rebuild {args.source}', recipe_text=recipe_text, sources=sources, input_file=(pathlib.Path(args.source), old.schema.name))
    write_database(new, output, record)
    print(f'\nRebuilt {len(report.added)} entries from original files, copied {len(copied)} from the old file: {output}')
    for line in copied:
        print(f'  copied (not rebuilt)  {line}')
    for line in report.notes:
        print(f'  note  {line}')

    comparison = compare(old, read_database(output))
    for difference in comparison.differences:
        source = ' [different source]' if difference.different_source else ''
        print(f'  {difference.change.value:22s} {difference.path}: {difference.message}{source}')
    counts = Counter(difference.change.value for difference in comparison.differences)
    print(f'Comparison with the old file: {comparison.identical} identical' + ''.join(f', {count} {change}' for change, count in sorted(counts.items())))
    return 0
