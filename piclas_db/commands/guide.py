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

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.git import GitError
from piclas_db.guide import guide
from piclas_db.recipe import RecipeError, load_recipe
from piclas_db.resolve import Origin, Requirement, resolve
from piclas_db.store import Store
# ==================================================================================================================================


def run(args: argparse.Namespace) -> int:
    """Step-by-step download instructions for original files, or for the files of a recipe that are missing in the store"""
    try:
        requirements = [Requirement.parse(text) for text in args.requirements]
        if args.recipe:
            recipe_requirements = load_recipe(args.recipe).requirements
            if args.all:
                requirements += recipe_requirements
            else:
                resolutions = resolve(Store(args.store), recipe_requirements, update=not args.offline)
                requirements += [resolution.requirement for resolution in resolutions if resolution.origin is Origin.MANUAL]
                if not requirements:
                    print('All original files of the recipe are in the store, nothing to download')
                    return 0
    except (ValueError, RecipeError, GitError) as e:
        print(f'ERROR: {e}')
        return 1
    if not requirements:
        print('Give original files (e.g. lxcat/biagi-v7.1/ar, nist-asd/levels/ar) or --recipe')
        return 1
    for requirement in requirements:
        print('\n'.join(guide(requirement)))
        print()
    print('Then import the downloads: piclas-db import --source-dir ~/Downloads')
    return 0
