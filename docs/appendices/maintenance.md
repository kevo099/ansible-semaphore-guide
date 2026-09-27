# Appendix: export, key rotation and upgrades

[Back to recovery](../10-recovery.md) · [Coverage](../COMMUNITY-COVERAGE.md)

## Goal

Move project configuration, rotate encryption keys and plan a recoverable upgrade.

| Item | Scope |
| --- | --- |
| Edition | Community 2.19.12 |
| Tested with | ansible-core 2.21.4; RHEL 9.8 controller, PostgreSQL 16, Ubuntu 24.04 target |
| UI or API path | Project backup/restore and task APIs; `semaphore project`, `vault` and `migrate` CLI |
| Evidence | [Portability and retention](../validation/2026-09-community.md#history-audit-and-portability), [rotation](../validation/2026-09-community.md#task-jwt-and-key-rotation), [version drill](../validation/2026-09-community.md#upgrade-and-rollback-drill) |
| Known limits | Exports omit Key Store values/history and lose fields; rekey backups cover only access-key ciphertexts; downgrade can leave tasks unusable. |

Finish [chapter 6](../06-semaphore.md) and take [chapter 10's private
capture](../10-recovery.md#a-private-application-capture). Use its [isolated
replacement](../10-recovery.md#restore-first-into-an-isolated-replacement),
blocking original-target access. Record settings privately and control all task
launches.

## Do: export and import a project

Project export/import is configuration portability. Key Store secret values,
Variable Group secrets, history/output, events, API tokens, membership and
runner registrations do not travel. External playbooks, inventory files and
controller configuration need separate handling. Recovery is chapter 10's
database, configuration, keys and runtime capture.

The tested paths are `GET /api/project/PROJECT_ID/backup` and `POST
/api/projects/restore`, with the JSON document as the restore body. Use an
unused `meta.name`: a duplicate returned HTTP 400. CLI export matched the API's
JSON content. API restore made the restoring user owner; CLI import made the
first database admin owner.

Treat exports as private: the test found a webhook alias in plain text. The pinned source
also permits ordinary variable values and some runner fields to contain credentials.
Project Guests could download backups in the test. Review membership accordingly.

**Where: controller, as your administrator account, on the isolated
replacement.** Prerequisites: the same 2.19.12 binary/schema, an existing
**Ansible Practice** project, and no project named **Portability practice**.
For this exercise use a source with no schedules or integrations; imported
schedules can become active. The CLI opens the database and applies pending
migrations, so do not use another version.

```bash
sudo bash <<'BASH'
set -euo pipefail
cd /
install -d -o semaphore -g semaphore -m 0700 /var/lib/semaphore/portability-practice
runuser -u semaphore -- sh -c '
  umask 077
  exec /usr/local/bin/semaphore project export \
    --config /etc/semaphore/config.json --project-name "Ansible Practice" \
    --file /var/lib/semaphore/portability-practice/project.json
'
runuser -u semaphore -- /usr/local/bin/semaphore project import \
  --config /etc/semaphore/config.json \
  --file /var/lib/semaphore/portability-practice/project.json \
  --project-name 'Portability practice'
BASH
```

Always supply `--file`; otherwise export prints the document. The CLI requests
mode 0644; `umask 077` makes this new file 0600 inside a directory only the
service account can open. This creates one imported project.

## Check: make the imported project runnable

**Where: browser, as the imported project's owner.** Inspect **Key Store**: names, types
and metadata return, but credential entries are empty. In the API restore test, Ping
failed with `secret must be valid json in key ...` until the SSH and sudo values were
re-entered privately. Then Ping reached the target and finished with no failures. Use
[chapter 15](../15-identity.md) to supply required values privately; check the
inventory, one-host limit and target recap again. The campaign used the API for
reinjection, not a browser walkthrough.

Review these boundaries before enabling any imported work:

| Item | What to check |
| --- | --- |
| Task history and events | They start empty; import cannot recover previous run evidence. |
| File inventory | The tested inventory lost its repository link. Reconnect it and supply the actual file. |
| Integration aliases | A collision with the source project's alias was silently dropped during API restore. |
| Template `jwt_params` | Pinned source writes populated settings as `{}`; enabled/audience/TTL do not survive. |
| One-time schedule `run_at` | Pinned source writes the timestamp as `{}`; rebuild it deliberately before scheduling. |
| Runners | Pinned source clears restored project-runner tokens; registration must be established separately. |

Populated JWT/schedule fields and runner restoration were not tested in this
export run. Restore is nontransactional in the pinned source: inspect for a
partial project after failure.

Cleanup: delete only **Portability practice**. **Where: controller, as your
administrator account.** Run `sudo rm -r /var/lib/semaphore/portability-practice`.
Retain chapter 10's capture under its policy.

## Do: rotate the encryption key

**Where: controller, as your administrator account, on the isolated
replacement.** This exercise starts with
the guide's single `access_key_encryption` value, no separate `option_encryption`, no
existing keyring and no `SEMAPHORE_*` environment overrides. Other arrangements were not
tested here. The initial `vault check` must be clean. Keep the old value in the private
configuration and recovery set. Never print key files or copy their contents into
commands, notes or messages.

```bash
sudo bash <<'BASH'
set -euo pipefail
cd /
runuser -u semaphore -- /usr/local/bin/semaphore vault check \
  --config /etc/semaphore/config.json
install -d -o root -g semaphore -m 0750 /etc/semaphore/keys
if [ ! -s /etc/semaphore/keys/ROTATION_KEY.key ]; then
  (umask 027; openssl rand -base64 32 > /etc/semaphore/keys/ROTATION_KEY.key)
fi
chown root:semaphore /etc/semaphore/keys/ROTATION_KEY.key
chmod 0640 /etc/semaphore/keys/ROTATION_KEY.key
BASH
```

This creates 32 random bytes in base64 without echoing them; existing nonempty
keys stay. Use a new label per rotation. Check the file as root; the key is
readable only by root and the `semaphore` group, which your account is not in:

```bash
sudo bash <<'BASH'
set -euo pipefail
key=/etc/semaphore/keys/ROTATION_KEY.key
if command -v restorecon >/dev/null; then restorecon -RF /etc/semaphore/keys; fi
stat -c '%U:%G %a' "$key"
base64 -d "$key" | wc -c
runuser -u semaphore -- test -r "$key" && echo 'The service account can read the key.'
BASH
```

Expect `root:semaphore 640`, `32` and the confirmation line. The registry and
configuration edits below also need root: open a root shell with `sudo -i`
for them, and leave it when the rotation is finished.

Create `/etc/semaphore/encryption-keys.json` with this initial registry. It references
the file; it contains no key material:

```json
{
  "keys": {"ROTATION_KEY": {"file": "/etc/semaphore/keys/ROTATION_KEY.key"}}
}
```

For each registry edit, write `/etc/semaphore/encryption-keys.json.new`, give it
`root:semaphore` ownership and mode 0640, then rename it over the destination. On
Enterprise Linux, apply `restorecon -F /etc/semaphore/encryption-keys.json`. Privately
merge this fragment into `/etc/semaphore/config.json`, preserving every existing
setting, especially `access_key_encryption`:

```json
{
  "encryption": {
    "keys_file": "/etc/semaphore/encryption-keys.json",
    "keys_poll_interval": "5s"
  }
}
```

Keep config ownership `root:semaphore` and mode 0640. Run `systemctl restart semaphore`
to load that main-config change. Then add `"active": {"secret_key": "ROTATION_KEY"}`
alongside `keys` using the same temporary-file/rename procedure. Keep the original key.

**Use `active.secret_key`.** The 2.19.12 `vault rekey --help` incorrectly names
`active.access_key`; the test showed that spelling was ignored. The five-second poller
applied the corrected pointer without a restart. Main-config changes still need a restart.

## Check: re-encrypt existing rows

Check `journalctl -u semaphore --since '5 minutes ago' --no-pager` locally for
`encryption keys reloaded (file changed)`, then run `vault check` again. The old key
should read `retired, rekey pending`. The CLI reading the new pointer alone does not
prove the running server loaded it: the test added a disposable **Rotation probe** Key
Store entry through the API and checked that the new key's row count increased. Ping
still succeeded while both keys were present.

For that optional probe, use [chapter 17's API workflow](../17-api-and-integrations.md)
and enter a disposable value privately. Pause other writers before rekeying. Reserve a
new private backup file; never overwrite an earlier rotation receipt:

```bash
sudo bash <<'BASH'
set -euo pipefail
cd /
install -d -o semaphore -g semaphore -m 0700 /var/lib/semaphore/rekey-backups
rotation_backup=$(runuser -u semaphore -- mktemp /var/lib/semaphore/rekey-backups/rotation.XXXXXX.jsonl)
runuser -u semaphore -- sh -c '
  umask 077
  exec /usr/local/bin/semaphore vault rekey --config /etc/semaphore/config.json \
    --backup "$1"
' sh "$rotation_backup"
runuser -u semaphore -- /usr/local/bin/semaphore vault check \
  --config /etc/semaphore/config.json
BASH
```

Require zero old-key rows, `retired, SAFE TO REMOVE`, no `legacy (no id)` rows, and an
active JWT slot if present. The backup holds only access-key ciphertexts, excluding the
JWT option and other database content. Rekey changes encryption across projects.

Run the credential-using Ping again, restart Semaphore and repeat it. The campaign also
removed the old flat key from the running configuration and proved Ping still decrypted
successfully. The task JWT signing key ID stayed unchanged: re-encrypting its stored key
did not rotate its signing identity.

**Keep old keys until every backup that needs them expires.** `SAFE TO REMOVE` describes
current database references, not retained captures or rekey backups. Include the keyring
and referenced files in future chapter 10 captures.

Cleanup: remove only your optional probe entry; real rotations retain their new key and
receipts. The campaign undid this exercise by stopping Semaphore, restoring the original
flat-key configuration plus a registry retaining both keys, and restarting with the
original key active. It rekeyed back, checked zero temporary-key references and the JWT
slot on the original key, then restored the original config byte for byte. Final Ping
passed. Removing the active pointer while the server lacks the original flat key can
leave new writes unencrypted. Retained backups may still need the temporary key.

## Do: set task retention and delete practice tasks

**Where: controller, as root, on the isolated replacement.** Retention is global
configuration applied per template. Save the previous setting; prevent other task
launches, including commit polling, before trying a small limit. Prerequisite: one
disposable template named **Retention practice**, created through chapter 6 with an
already qualified harmless playbook. Merge `"max_tasks_per_template": 3` into the main
configuration and restart Semaphore. Zero disables automatic pruning.

**Where: browser, as a project Manager.** Run only that template five times, waiting for
each to finish, and check History for the newest three tasks. The campaign's harmless
local play kept three. Pruned tasks and their output returned HTTP 400; their six task
events remained. Increasing the limit later cannot recover deleted output.

The pinned source prunes on task creation, not on an age-based timer. It uses a 10%
threshold and a timestamp cutoff, so larger limits are not a strict always-exactly-N
guarantee. It does not filter pruning by task status.

For explicit deletion, only a server administrator may use `DELETE
/api/project/PROJECT_ID/tasks/TASK_ID`; a project Manager was refused. The tested
deletion removed task/output, retained existing events and wrote no deletion event. Use
chapter 17's private authentication and select only your exercise task. See [history and
activity](../16-semaphore-operations.md#check-read-task-history-and-the-activity-log).

**Where: controller, as root.** Cleanup: restore the previous retention setting and
restart before reopening other launches. **Where: browser/API, as a server
administrator.** Delete only the remaining practice tasks, then the **Retention
practice** template. Neither project export nor surviving events preserves task output.

## Do: rehearse an upgrade on a restored copy

**Where: browser/API as administrator, then controller as root.** Use [chapter 10's
isolated restore](../10-recovery.md#restore-first-into-an-isolated-replacement) first.
Record versions, schema and a successful authenticated Ping. Before the real change,
pause schedules/integrations, prevent manual launches and wait for an empty live task
pool (`GET /api/tasks` as admin). Commit-check schedules need special care: the pinned
source still polls them with `active: false`; remove the exact polling schedules after
recording their settings, or keep the copy isolated. Take chapter 10's capture before
changing the binary or database.

## Concept: why a downgrade is not a rollback

The tested drill was 2.19.12 → 2.18.30 → 2.19.12. With Semaphore stopped, the 2.19.12
binary accepted `semaphore migrate --undo-to 2.18`, then the exact target `2.18.5`. The
short form retains all 2.18.x migrations; it was not enough for 2.18.30. A `v2...`
prefix or combining `--undo-to` with `--apply-to` was refused without changing
migrations. These are observations, not a rollback recipe.

The source can exit zero even when undo fails; this failure was not induced in the drill.
Check the `migrations` table and affected schema, not just status or “Rollback Finished”.

After the schema downgrade, 2.18.30 allowed login and project/template reads, but the
tested Ping failed with `illegal base64 data`. The source explains why: 2.19 stores Key
Store values in a key-ID envelope that 2.18 cannot decode. Tasks needing those
credentials cannot run merely because the old UI opens.

Returning to 2.19.12 reapplied migrations, retained the tested data and schema, and ran
Ping successfully. The version-switch interval was 18 seconds, excluding capture
downtime and the final Ping check. Newer fields were empty in this dataset; this does
not prove populated newer data survives a downgrade.

For a failed upgrade, restore chapter 10's matching pre-upgrade capture and
runtime, then prove a credential-using task. Do not use `--undo-to` as your
recovery plan. Future-version upgrades were not tested. Whole-database flags
`--err-log-size`, `--skip-task-output` and `--merge-existing-users` are parsed
but unused in 2.19.12. Remove only the isolated rehearsal copy after its checks;
retain the capture under its policy.
