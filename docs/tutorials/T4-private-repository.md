# T4 The private source repository

The store can be a clone of a private git repository of your group: every import is then a commit, the originals are backed up,
and everybody in the group builds from the same files. The repository is never public (LXCat, NIST and papers must not be
redistributed).

Prerequisites: [T1](T1-getting-started.md) steps 1 and 2; an SSH key that has access to your GitHub organisation.

## 1. Create the repository (once per group)

On GitHub, in your organisation: *New repository*

* name, e.g. `piclas-db-sources`
* visibility **Private**
* **no** README, licence or `.gitignore` (an empty repository)

Then give the members of the group access (*Settings → Collaborators and teams*): *Write* for those who add data, *Read* for those
who only build.

## 2. Check your SSH access

```bash
ssh -T git@github.com            # "Hi <name>! You've successfully authenticated ..."
```

piclas-db never asks for passwords: git runs with your SSH key and fails at once if access is missing.

## 3. Connect your store

```bash
piclas-db config --set mirror git@github.com:<org>/piclas-db-sources.git
piclas-db fetch
```

```
Store: /home/ada/piclas-db-store: cloned from git@github.com:<org>/piclas-db-sources.git
0 file(s) in the store, in sync with the private repository
```

* An **empty** store becomes a clone (also of an empty repository).
* An **existing** store (e.g. from T1) is adopted: the repository is cloned next to it, your files that are not in the repository yet
  are added in one commit, and the old directory is kept as `<store>.backup-<date>`.

## 4. Add data and back it up

```bash
piclas-db import --source-dir ~/Downloads      # one commit per file, author: your piclas-db user
piclas-db push
```

```
Pushed 2 commit(s) to git@github.com:<org>/piclas-db-sources.git
```

`push` refuses to push if a file no longer matches its sha256 (`piclas-db store --verify` shows which).

## 5. Work in a group

```bash
piclas-db fetch                                                   # get what the others added
piclas-db fetch --need lxcat/phelps/n2 nist-asd/levels/arion1     # where are these files?
piclas-db build recipe.yaml -o database.h5                        # updates from the repository if something is missing
```

`fetch --need` and `build` look for every original file in this order: local store → private repository → (automatic download, not
available yet) → manual download with `piclas-db guide`. Imports only add new files, so two people importing at the same time do not
get conflicts: `fetch` and `push` rebase.

## Without access

Everything works without the private repository: the store is then only local. Back it up yourself, or connect it later (step 3
adopts it).

## Troubleshooting

| Message | Meaning |
|---|---|
| `no access: check your SSH key and your permissions for the private repository` | SSH key not added to GitHub, or no access to the repository |
| `the store is a clone of ..., not of ...` | `mirror` in the configuration differs from the remote of the store |
| `Not pushed: the store contains changed or missing files` | a file in the store was modified: `piclas-db store --verify` |
| `Please tell piclas-db who you are` | `piclas-db config --set user.name/user.email` |
| `WARNING: store not updated from the private repository (git pull failed: ... commit or stash them)` | the clone has uncommitted changes: `piclas-db store` lists them, `piclas-db store --commit` commits store files (e.g. after a failed import), anything else remove by hand |
