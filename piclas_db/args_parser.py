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
from piclas_db.commands import COMMANDS
from piclas_db.common.common_vars import Common
# ==================================================================================================================================


def build_parser() -> argparse.ArgumentParser:
    """Command-line interface: one sub-command per task"""
    common = Common()
    parser = argparse.ArgumentParser(
        prog=common.program,
        description='Build, check and convert PICLas species and cross-section databases (database.h5) from original sources such as LXCat and NIST.',
        epilog=f'Run "{common.program} <command> --help" for the options of a command.',
    )
    parser.add_argument('-v', '--version', action='version', version=common.version_string())

    subparsers = parser.add_subparsers(dest='command', metavar='<command>')
    for name, command in COMMANDS.items():
        sub = subparsers.add_parser(name, help=command.help, description=command.help)
        if name == 'check':
            sub.add_argument('file', help='database file (.h5) to check')
            sub.add_argument('--info', action='store_true', help='also show findings of severity INFO')
            sub.add_argument('--json', action='store_true', help='print the findings as JSON')
        elif name == 'guide':
            sub.add_argument('requirements', nargs='*', metavar='PROVIDER/DATASET', help='original files, e.g. lxcat/biagi-v7.1/ar or nist-asd/levels/arion1')
            sub.add_argument('--recipe', help='show the instructions for the files of this recipe that are missing in the store')
            sub.add_argument('--all', action='store_true', help='with --recipe: all files of the recipe, also those in the store')
            sub.add_argument('--store', help='local store (default: $PICLAS_DB_STORE or ~/.local/share/piclas-db/store)')
            sub.add_argument('--offline', action='store_true', help='do not update the store from the private repository')
        elif name == 'rebuild':
            sub.add_argument('source', help='existing database (any layout)')
            sub.add_argument('-o', '--output', help='rebuilt database file (.h5); not with --explain')
            sub.add_argument('--recipe-out', help='file for the derived recipe (default: <output>.recipe.yaml; with --explain: no recipe unless given)')
            sub.add_argument('--explain', action='store_true', help='compare every cross-section with everything in the store and report where it comes from')
            sub.add_argument('--report', help='with --explain: Markdown report file')
            sub.add_argument('--levels-from-nist', action='store_true', help='rebuild all electronic levels from NIST ASD (also without NIST reference)')
            sub.add_argument('--derive', action='store_true', help='derive the recipe from the provenance even if the file contains its recipe')
            sub.add_argument('--allow-unreviewed', action='store_true', help='also use extractions and rate tables that have not been reviewed yet')
            sub.add_argument('--store', help='local store (default: $PICLAS_DB_STORE or ~/.local/share/piclas-db/store)')
            sub.add_argument('--offline', action='store_true', help='do not update the store from the private repository')
            sub.add_argument('--force', action='store_true', help='overwrite an existing output file')
        elif name == 'import':
            sub.add_argument('--color', choices=['auto', 'always', 'never'], default=None, help='colors: auto (on a terminal, default), always (also into a pipe, e.g. tee), never')
            sub.add_argument('files', nargs='*', help='downloaded files (LXCat, NIST ASD, ...)')
            sub.add_argument('--source-dir', help='directory to search for downloaded files (e.g. ~/Downloads); unknown files are skipped')
            sub.add_argument('--store', help='local store (default: $PICLAS_DB_STORE or ~/.local/share/piclas-db/store)')
            sub.add_argument('--species', help='species of a NIST ASD level file if not found in the file or its name (e.g. ArIon1)')
            sub.add_argument('--custom', metavar='NAME', help='store files that are not recognized (e.g. own data) under custom/NAME')
            sub.add_argument('--retrieved', metavar='YYYY-MM-DD', help='retrieval date if not contained in the file')
            sub.add_argument('--literature', nargs='?', const='', metavar='KEY', help='store a paper (PDF) under literature/KEY, e.g. yoon-2008 (without KEY: first author and year from Crossref)')
            sub.add_argument('--doi', help='with --literature: DOI of the paper (default: found in the PDF, its name or at Crossref)')
            sub.add_argument('--reference', help='with --literature: citation of the paper (default: from Crossref for the DOI)')
            sub.add_argument('--review', action='store_true', help='with --literature: after the overview, decide paper by paper (open the DOI link, import, correct, skip)')
            sub.add_argument('--checklist', metavar='FILE', help='with --literature: write the overview as a Markdown checklist')
            sub.add_argument('--new-version', action='store_true', help='with --literature: keep a file of a paper that is already in the store (same DOI or text) as another version under its key')
            sub.add_argument('--no-lookup', action='store_true', help='with --literature: do not ask Crossref (DOI from the PDF or its name only, unchecked)')
            sub.add_argument('-n', '--dry-run', action='store_true', help='only show what would be imported (with --review: decide now, import later)')
        elif name == 'build':
            sub.add_argument('recipe', help='recipe (YAML): original files and their selection')
            sub.add_argument('-o', '--output', required=True, help='database file to write (.h5)')
            sub.add_argument('--store', help='local store (default: $PICLAS_DB_STORE or ~/.local/share/piclas-db/store)')
            sub.add_argument('--offline', action='store_true', help='do not update the store from the private repository')
            sub.add_argument('--force', action='store_true', help='overwrite an existing output file')
            sub.add_argument('--allow-unreviewed', action='store_true', help='also use extractions from papers that have not been reviewed yet')
            sub.add_argument('--plot-parts', metavar='DIR', help='write a plot of every dataset combined from several extractions into DIR')
            sub.add_argument(
                '--layout',
                choices=['species-database', 'xsec'],
                default='species-database',
                help='species-database (Particles-Species-Database, default) or xsec (cross-sections only, for Particles-CollXSec-Database)',
            )
        elif name == 'literature':
            sub.add_argument(
                'action',
                choices=['template', 'add', 'review', 'list', 'want', 'wanted', 'unwant'],
                help='template: files to enter data; add: store an extraction; review: approve or reject; list; want: put a paper on the wanted list; wanted: show it; unwant: remove an entry',
            )
            sub.add_argument('arguments', nargs='*', help='template: PAPER NAME; add: RECORD.yaml; review: PAPER/NAME[@SHA]; want, unwant: KEY')
            sub.add_argument('--reference', help='want: citation of the wanted paper')
            sub.add_argument('-n', '--dry-run', action='store_true', help='add: check the record and show the rows as understood, store nothing')
            sub.add_argument('--compare', metavar='DATABASE', help='add -n of a rate table: compare every row with the reactions of this database')
            sub.add_argument('--doi', help='want: DOI of the wanted paper (its import then removes the entry)')
            sub.add_argument('--needed-for', help='want: what the paper is needed for')
            sub.add_argument('--note', help='want: a note, e.g. a failed download attempt (added to earlier notes)')
            sub.add_argument('--page', help='template: page in the PDF (and the printed page label, e.g. "14 (926)")')
            sub.add_argument('--table', help='template: table number')
            sub.add_argument('--figure', help='template: figure number')
            sub.add_argument('--equation', help='template: equation number of a fit formula, e.g. 209')
            sub.add_argument('--formula', action='store_true', help='template: a fit formula instead of a table (writes <name>.formula.yaml)')
            sub.add_argument('--rates', action='store_true', help='template: a reaction rate table (Arrhenius parameters per reaction and third body)')
            sub.add_argument('--parameters-from', metavar='PAPER/TABLE', help='template --formula: parameters from a stored parameter table')
            sub.add_argument('--column', help='template --formula: column of the parameter table (header text or number, 1 = first value column)')
            sub.add_argument('--method', default='manual', help='template: manual, text, ocr, vector or raster (default manual)')
            sub.add_argument('-o', '--output', default='.', help='template: directory for the files (default .)')
            sub.add_argument('--approve', action='store_true', help='review: approve')
            sub.add_argument('--reject', action='store_true', help='review: reject')
            sub.add_argument('--reviewer', help='review: name of the reviewer')
            sub.add_argument('--notes', help='review: notes')
            sub.add_argument('--store', help='local store (default: $PICLAS_DB_STORE or ~/.local/share/piclas-db/store)')
        elif name == 'extract':
            sub.add_argument('paper', nargs='?', help='paper in the store (key given to import --literature)')
            sub.add_argument('--page', help='page of the PDF (1-based); for tables also ranges such as 14-15 (continued tables)')
            sub.add_argument('--redo', metavar='PAPER/DATASET[@SHA]', help='run a stored extraction again with this version and compare it with the stored one')
            sub.add_argument('--table', help='extract table <number> (e.g. 12) instead of a figure')
            sub.add_argument('--ocr', action='store_true', help='with --table: read the page by OCR even if it has a text layer')
            sub.add_argument('--raster', action='store_true', help='treat the page as a scan (default: automatic for pages without vector graphics)')
            sub.add_argument('--frame-box', help='scans: frame x0,y0,x1,y1 in pt (from the grid image of --list) if it is not found')
            sub.add_argument('--x-points', help='scans: calibration points of the x axis "pt=value,pt=value" (from the grid image)')
            sub.add_argument('--y-points', help='scans: calibration points of the y axis "pt=value,pt=value" (from the grid image)')
            sub.add_argument('--seeds', help='scans: one curve per seed "x,y" or "x,y,x2,y2" (two points give the direction), curves separated by ";", in axis values')
            sub.add_argument('--symbol-radius', type=int, default=2, help='scans: radius in pixels at 300 dpi below which lines and text are removed (default 2)')
            sub.add_argument('--frame', type=int, default=0, help='plot frame on the page, see --list (default 0: top left)')
            sub.add_argument('--list', action='store_true', help='list the plot frames with data on the page')
            sub.add_argument('--figure', help='figure number for the record, e.g. 3')
            sub.add_argument('--name', help='prefix of the dataset names (default p<page>-f<frame>)')
            sub.add_argument('--x-labels', help='values of the major x ticks, comma separated, if they cannot be read')
            sub.add_argument('--y-labels', help='values of the major y ticks, comma separated, if they cannot be read')
            sub.add_argument('--x-scale', choices=['linear', 'log'], help='scale of the x axis (default: from the labels)')
            sub.add_argument('--y-scale', choices=['linear', 'log'], help='scale of the y axis (default: from the labels)')
            sub.add_argument('--x-unit', default='eV', help='unit of the x axis: eV, keV, or a velocity m/s, cm/s, a.u. (then --mass-amu)')
            sub.add_argument('--x-quantity', default='energy', help='quantity on the x axis, e.g. "projectile energy (lab)", "velocity"')
            sub.add_argument('--mass-amu', type=float, help='projectile mass in amu, to convert a velocity axis to energy')
            sub.add_argument('--target-mass-amu', type=float, help='target mass in amu: laboratory energies are converted to the collision energy PICLas uses')
            sub.add_argument('--energy-frame', choices=['collision', 'lab'], help='energy frame of the x axis (default: lab for velocities, collision for energies)')
            sub.add_argument('--y-unit', default='1e-16 cm^2', help='unit of the y axis, e.g. "1e-16 cm^2", "A^2", "m^2"')
            sub.add_argument('--by', help='who extracts (for the record)')
            sub.add_argument('-o', '--output', default='.', help='directory for the CSV files, records and review image')
            sub.add_argument('--store', help='local store (default: $PICLAS_DB_STORE or ~/.local/share/piclas-db/store)')
        elif name == 'fetch':
            sub.add_argument('--mirror', help='private repository (git URL, e.g. git@github.com:<org>/<repo>.git; default: $PICLAS_DB_MIRROR)')
            sub.add_argument('--need', nargs='+', default=[], metavar='PROVIDER/DATASET[@SHA]', help='locate these original files')
            sub.add_argument('--store', help='local store (default: $PICLAS_DB_STORE or ~/.local/share/piclas-db/store)')
        elif name == 'push':
            sub.add_argument('--store', help='local store (default: $PICLAS_DB_STORE or ~/.local/share/piclas-db/store)')
        elif name == 'atct':
            sub.add_argument('action', choices=['search', 'get', 'map'], help='search: find species by name or formula; get: download records by ATcT ID; map: ATcT IDs for the species of a database')
            sub.add_argument('arguments', nargs='+', help='search: name or formula (e.g. carbon monoxide); get: ATcT IDs (e.g. 630-08-0*0); map: database file (.h5)')
            sub.add_argument('--all', action='store_true', help='search: also species that are not in the gas phase')
            sub.add_argument('--species', nargs='+', help='map: only these species (default: all whose reference credits ATcT)')
            sub.add_argument('--tolerance', type=float, default=1.0, help='map: accepted difference of the heat of formation in kJ/mol (default 1.0)')
            sub.add_argument('--recipe-out', help='map: write recipe entries (matched species with their ATcT ID, the others as comments)')
            sub.add_argument('--own-data', default='own/piclas-parameters', help='map: own data named in the recipe (default own/piclas-parameters, "" for none)')
            sub.add_argument('--get', action='store_true', help='map: download the records of the matched species into the store')
            sub.add_argument('--store', help='local store (default: $PICLAS_DB_STORE, configuration, ~/.local/share/piclas-db/store)')
        elif name == 'config':
            sub.add_argument('--init', action='store_true', help='write a commented template of the configuration file')
            sub.add_argument('--set', nargs=2, metavar=('KEY', 'VALUE'), help='set a value, e.g. user.name "Your Name", user.email, store, mirror, extract.by')
            sub.add_argument('--unset', metavar='KEY', help='remove a value')
        elif name == 'store':
            sub.add_argument('--store', help='local store (default: $PICLAS_DB_STORE or ~/.local/share/piclas-db/store)')
            sub.add_argument('--verify', action='store_true', help='check that every file still matches its sha256')
            sub.add_argument('--commit', action='store_true', help='commit store files that were not committed (e.g. after a failed import)')
        elif name == 'export':
            sub.add_argument('source', help='database file (.h5) of any layout')
            sub.add_argument('-o', '--output', help='new or empty directory for the tables')
            sub.add_argument('--own-data', metavar='FILE', help='write the species attributes as an own-data file (YAML) for the store')
            sub.add_argument('--origin', help='with --own-data: name of the file in every Reference (default: file name and modification date)')
            sub.add_argument('--name', default='piclas-parameters', help='with --own-data: dataset name in the store (default: piclas-parameters)')
            sub.add_argument('--keep-atct', action='store_true', help='with --own-data: keep heats of formation and masses that the file credits to ATcT')
            sub.add_argument('--levels', action='store_true', help='with --own-data: also the levels no level source provides (molecules, dummy levels of bare nuclei, vibrational levels)')
            sub.add_argument('--atct-from', metavar='RECIPE', help='with --own-data: also leave out heat of formation and mass of the species with an ATcT ID in this recipe')
            sub.add_argument('--force', action='store_true', help='with --own-data: overwrite an existing file')
        elif name == 'migrate':
            sub.add_argument('source', help='database file (.h5) of any layout, or a directory with ASCII tables')
            sub.add_argument('-o', '--output', required=True, help='new database file (.h5)')
            sub.add_argument('--fix', action='store_true', help='rename typos in group and attribute names, sort electronic levels')
            sub.add_argument('--canonical-products', action='store_true', help='rename reaction cross-sections to heavy species first, electrons last')
            sub.add_argument('--force', action='store_true', help='overwrite an existing output file')
        elif name == 'plot':
            sub.add_argument('sources', nargs='+', help='database files (any layout), table directories or original LXCat/NIST ASD downloads')
            sub.add_argument('--pair', help='collision pair, e.g. Ar-electron (order does not matter)')
            sub.add_argument('--species', help='electronic levels of this species (also the species of a NIST ASD file)')
            sub.add_argument('--kind', nargs='+', choices=['EFFECTIVE', 'ELASTIC', 'BACKSCATTER', 'ROTATION', 'VIBRATION', 'ELECTRONIC', 'REACTION', 'SPECTRUM', 'UNDEFINED'], help='only these kinds')
            sub.add_argument('--key', help='only cross-sections whose name contains this text (threshold or products)')
            sub.add_argument('--compare', action='store_true', help='additional panel with the deviation from the first source')
            sub.add_argument('--rate', action='store_true', help='Maxwellian rate coefficients k(T) instead of cross-sections')
            sub.add_argument('--temperatures', default='1e3:1e5', help='temperature range for --rate: start:stop[:count] in K (default 1e3:1e5)')
            sub.add_argument('--label', nargs='+', help='legend labels, one per source (default: file names)')
            sub.add_argument('--list', action='store_true', help='list the collision pairs and species of the sources')
            sub.add_argument('--parts', action='store_true', help='datasets combined from several extractions: parts, ranges, full source data, seams')
            sub.add_argument('--explain', nargs='+', metavar='SOURCE', help='which of these sources (extractions in the store or files) each point of one dataset (--pair, --key) comes from')
            sub.add_argument('--store', help='local store for the source data of --parts (default: $PICLAS_DB_STORE, configuration, ~/.local/share/piclas-db/store)')
            sub.add_argument('-o', '--output', default='piclas-db-plot.png', help='image file (.png, .pdf, .svg; default piclas-db-plot.png)')
        elif name == 'reservoir':
            sub.add_argument('database', nargs='?', help='database file (complete species database with MassIC)')
            sub.add_argument('--pair', help='collision pair with reaction cross-sections, e.g. Ar-electron')
            sub.add_argument('--projectile', help='moving species (default: electron or the ion of the pair)')
            sub.add_argument('--reactions', nargs='+', metavar='PRODUCTS', help='only these reaction cross-sections, e.g. ArIon1-electron-electron')
            sub.add_argument('--energies', nargs='+', metavar='E', help='collision energies in eV (beam mode), numbers or start:stop:count')
            sub.add_argument('--temperatures', nargs='+', metavar='T', help='temperatures in K (Maxwell mode), numbers or start:stop:count')
            sub.add_argument('--background-density', type=float, default=1.0e22, help='density of the background gas in m^-3 (default 1e22)')
            sub.add_argument('--projectile-density', type=float, default=1.0e21, help='density of the projectiles in m^-3 (default 1e21)')
            sub.add_argument('--events', type=float, default=1.0e4, help='counted reactions aimed for per point (default 1e4, about 1 %% statistical error)')
            sub.add_argument('--collision-probability', type=float, default=0.01, help='maximum collision probability per time step (default 0.01, rate bias about -0.5 %%)')
            sub.add_argument('-o', '--output', help='new directory for the study')
            sub.add_argument('--evaluate', metavar='DIRECTORY', help='evaluate a finished study')
            sub.add_argument('--regressioncheck', nargs='+', metavar='DIRECTORY', help='compare the reference results of PICLas reservoir regression checks with DATABASE (default: the database of each check)')
            sub.add_argument('--tolerance', type=float, default=0.05, help='relative tolerance for the evaluation (default 0.05)')
        elif name == 'diff':
            sub.add_argument('--color', choices=['auto', 'always', 'never'], default=None, help='colors: auto (on a terminal, default), always (also into a pipe, e.g. tee), never')
            sub.add_argument('a', help='first database (A): file of any layout, table directory or original LXCat/NIST ASD download')
            sub.add_argument('b', help='second database (B), as A')
            sub.add_argument('--rtol', type=float, default=1.0e-6, help='relative tolerance for identical values (default: 1e-6, covers float32)')
            sub.add_argument('--all', action='store_true', help='also report categories that exist in only one of the files')
            sub.add_argument('--json', action='store_true', help='print the differences as JSON')

    return parser
