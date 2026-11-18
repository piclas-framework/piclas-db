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
import pathlib
from collections import Counter

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db import provenance
from piclas_db.build import BuildError, build
from piclas_db.git import GitError
from piclas_db.readers import read_database
from piclas_db.recipe import RecipeError, load_recipe
from piclas_db.resolve import Origin, resolve
from piclas_db.rules import Severity, run_checks
from piclas_db.store import Store
from piclas_db.writer import write_database, write_xsec_database
# ==================================================================================================================================


def run(args: argparse.Namespace) -> int:
    """Build a database from the original files in the store according to a recipe"""
    output = pathlib.Path(args.output)
    if output.exists() and not args.force:
        print(f'ERROR: {output} exists (use --force to overwrite)')
        return 1
    store = Store(args.store)
    try:
        recipe = load_recipe(args.recipe)
        resolutions = resolve(store, recipe.requirements, update=not args.offline)
    except (RecipeError, GitError) as e:
        print(f'ERROR: {e}')
        return 1

    for resolution in resolutions:
        location = resolution.entry.relative if resolution.entry else 'missing: download by hand, then piclas-db import'
        print(f'  {resolution.origin.value:20s} {resolution.requirement}: {location}')
    if any(resolution.origin is Origin.MANUAL for resolution in resolutions):
        print('ERROR: original files are missing in the store')
        return 1

    try:
        database, report = build(recipe, resolutions, allow_unreviewed=args.allow_unreviewed)
    except BuildError as e:
        print(f'ERROR: {e}')
        return 1
    sources = [(str(resolution.requirement), resolution.entry.relative, str(resolution.entry.meta.get('sha256')), resolution.entry.meta.get('retrieved')) for resolution in resolutions if resolution.entry is not None]
    recipe_text = pathlib.Path(args.recipe).read_text(encoding='utf-8')
    record = provenance.create(f'build {args.recipe}' + (' --layout xsec' if args.layout == 'xsec' else ''), recipe_text=recipe_text, sources=sources)
    if args.layout == 'xsec':
        # cross-sections only, collision pairs at the root: for Particles-CollXSec-Database (species from parameter.ini)
        skipped = write_xsec_database(database, output, record)
        if skipped:
            print(f'  note   not written in the xsec layout: {", ".join(skipped)}')
    else:
        write_database(database, output, record)

    for line in report.added:
        print(f'  added  {line}')
    for line in report.notes:
        print(f'  note   {line}')
    counts = Counter(finding.severity for finding in run_checks(read_database(output)))
    print(f'{output}: {len(report.added)} entries; check: {counts[Severity.ERROR]} error(s), {counts[Severity.WARNING]} warning(s)')
    return 0
