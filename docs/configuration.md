# Configuration

Settings that would otherwise be repeated on every command line go into a configuration file:

```bash
piclas-db config --init     # writes a commented template
piclas-db config            # shows the file and the settings in effect (and where they come from)
```

Location: `~/.config/piclas-db/config.yaml` (`$XDG_CONFIG_HOME/piclas-db/config.yaml`), or the file named by `$PICLAS_DB_CONFIG`.

```yaml
user:                        # who adds data: required for import, extract and literature add/review (like git config user.*)
  name: Stephen Copplestone
  email: stephen@example.org
store: ~/data/piclas-db-store                                   # local store of original files
mirror: git@github.com:piclas-framework/piclas-db-sources.git   # private source repository
extract:                     # defaults for the options of a command: option names as on the command line ('-' or '_')
  by: Stephen Copplestone
literature:
  reviewer: Stephen Copplestone
reservoir:
  collision-probability: 0.01
  tolerance: 0.05
```

Set values without editing the file: `piclas-db config --set user.name "Your Name"`, `--set user.email ...`, `--set store ...`,
`--set extract.by ...`; remove them with `--unset KEY`. Instead of `user.*`, `$PICLAS_DB_USER_NAME` and `$PICLAS_DB_USER_EMAIL`
can be set. The user is recorded as `imported_by`, `created.by` and reviewer, and is the author of the commits in a store that
is a clone of the private repository.

Order of precedence: command line, then environment variables (`$PICLAS_DB_STORE`, `$PICLAS_DB_MIRROR`), then the configuration
file, then the built-in defaults. A command section may set any option of that command (`piclas-db <command> --help`); unknown
entries and options are reported as warnings and ignored. The configuration never contains credentials: access to the private
repository is through SSH keys.
