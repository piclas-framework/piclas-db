# Design: LXCat downloads in TXT and XML, combined databases and growing downloads

Status: implemented in piclas-db 0.26.0 (sections 1–3). Checked with a ZIP from LXCat (Biagi-v7.1 + Phelps, Ar, 18 Nov 2026):
TXT and XML contain the same 10 processes with identical tables, and the databases built from the TXT, the XML and the ZIP are
identical (data and every attribute apart from the stored source file). LXCat marks its XML as *under development*; a ZIP is
therefore read from its TXT, and the XML is the independent check.

## Requirements

1. LXCat offers the same selection as TXT and as XML (both in one ZIP). Both must be accepted and must give **exactly the same
   dataset** in piclas-db.
2. One download can contain several databases (e.g. Biagi-v7.1 + Phelps). The XML distinguishes them explicitly, the TXT by its
   `DATABASE:` sections. Each process must keep its database.
3. Downloads grow: somebody first downloads *Elastic* and *Excitation*, later *Ionization* of the same database and species. The
   later file must add to what is there, without duplicates and without hiding conflicts.

## 1. One model for TXT and XML

Both formats are parsed into the same internal model, one record per process:

| Field | TXT | XML |
|---|---|---|
| database | `DATABASE:` of the section | database element |
| species (projectile / target) | `SPECIES: e / Ar` | species elements |
| type | keyword (`ELASTIC`, …) or end of `PROCESS:` | process type |
| process | `PROCESS:` | reaction / process text |
| parameters | `PARAM.:` (threshold, mass ratio) | parameter elements |
| updated | `UPDATED:` | update time |
| data | table between dashes | data points |

**Identity of a process (fingerprint):** database, species, process and update time. The update time is unique per LXCat process
(already used by `rebuild`).

**Equality check:** a ZIP with TXT and XML is imported as **one original file** (the ZIP, byte for byte, as downloaded). On import,
both files inside are parsed and compared process by process: same fingerprints, same tables (to the precision printed in the TXT).
If they differ, the import fails with the list of differences. The `meta.yaml` records which files the ZIP contains and that they
agree. A TXT or XML alone is imported as before.

**Same dataset:** recipes and builds only see the model, never the format. A database built from the TXT, from the XML or from the
ZIP is identical (test: the three builds are compared with `diff` and must be identical, including the provenance of every process
apart from the file name and sha256).

## 2. Several databases in one file

Every process keeps its database, so a combined download (Biagi + Phelps) is never mixed up: recipes select by `database` and
`species` (as today). The store keeps the file under the combination of databases (as today: `lxcat/biagi-v7.1+phelps/ar/`), but
the lookup works per process (next section), so it does not matter how the data were grouped when they were downloaded.

## 3. Growing downloads: a process index over all LXCat files

The store gets an **index of all LXCat processes** in all downloads (generated, like `index.yaml`):

```
fingerprint (database, species, process, updated) -> file (sha256), retrieval date, type, threshold
```

A recipe can then ask for data by database and species, independent of the files:

```yaml
cross_sections:
  - source: lxcat              # all LXCat downloads in the store (new)
    database: Biagi-v7.1
    species: e / Ar
    processes: [Elastic, Excitation, Ionization]   # optional: what must be there
  - source: lxcat/biagi-v7.1+phelps/ar             # one file, as today (still valid)
    database: Phelps
    species: Ar^+ / Ar
```

Rules when several files contain processes of the same database and species:

| Case | Behaviour |
|---|---|
| Different processes (first Elastic + Excitation, later Ionization) | **union**: all processes are used; the provenance of every dataset names the file it came from |
| Same fingerprint, same table | duplicate: taken once (from the newest file), the others are listed |
| Same process, newer update time | newest wins, reported in the build ("Ionization updated 2011-01-19 → 2024-…") |
| Same fingerprint, **different** table | **conflict**: build stops and names both files; pin one with `@sha256` |
| Expected process missing (`processes:`) | build stops; `guide` and `fetch --need` say which download is missing |

`import` reports what a new file adds: *"3 new processes for Biagi-v7.1 e/Ar (IONIZATION …), 4 already in the store"*.

`rebuild` and the header fingerprints already work per process, so they profit directly.

## 4. Provenance

Every dataset built from LXCat names its original file and sha256 (as today), and with the index also the fingerprint. A database
built from several downloads therefore lists several files in `* piclas-db sources`.

## 5. What is needed

* A ZIP downloaded from LXCat with TXT and XML for Biagi-v7.1 + Phelps, Ar (the same selection as the GEC tutorial).
* A second download of the same database and species with only some processes (e.g. Elastic and Excitation), and one with the rest
  (Ionization), to test the growing case.
* Optionally a download made at a different time (to see changed update times).

## Steps

1. XML parser and ZIP import with the equality check (tests: TXT vs XML vs ZIP give identical builds).
2. Process index in the store, `source: lxcat` in recipes, rules of section 3, `import` report.
3. `guide`/`fetch --need` per process.
