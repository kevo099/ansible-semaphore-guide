# Semaphore Community 2.19.12 coverage

[Back to the guide](../README.md) · [Validation and limits](VALIDATION.md) · [Campaign record](validation/2026-09-community.md)

This table lists what Semaphore Community 2.19.12 offers beyond the first job
in chapter 6, whether each capability is free, what the September 2026 live
test showed, and where the guide teaches it. Pricing pages describe newer
releases and change over time; this table describes the pinned binary.

**Edition:** *Community* works in the free Community build; *paid* is a
stub, a 404 or a licence check in 2.19.12; *absent* means 2.19.12 does not
have it at all.

**Live result:** *passed* means the campaign ran it and saw the effect, not
just an HTTP success; *caveats* means it works with a sharp edge you should
read about before relying on it; *not tested* means the capability exists but
the campaign did not exercise it.

## Inputs and templates

| Capability | Edition | Live result | Guide |
| --- | --- | --- | --- |
| Several variable groups per template | Community | caveats: later-created group wins on duplicate keys | [14](14-inputs-and-templates.md) |
| Variable-group secrets (`var`, `env`) | Community | caveats: not masked if printed; `var` values visible in the controller's process list | [14](14-inputs-and-templates.md), [15](15-identity.md) |
| Surveys: string, integer, text, enum, defaults, `env` target | Community | caveats: rules enforced by the UI only; values evaluated as templates | [14](14-inputs-and-templates.md) |
| Limit, branch and argument overrides | Community | passed; ignored unless the template allows them | [14](14-inputs-and-templates.md) |
| Template views | Community | not tested | [14](14-inputs-and-templates.md) |
| Build and Deploy templates, autorun | Community | passed | [14](14-inputs-and-templates.md) |
| Bash and Python templates | Community | passed | [other apps](appendices/other-apps.md) |
| OpenTofu with plan confirmation | Community | passed | [other apps](appendices/other-apps.md) |
| Terragrunt | Community | passed | [other apps](appendices/other-apps.md) |
| Terraform, PowerShell | Community | not tested | [other apps](appendices/other-apps.md) |
| Pulumi | absent | refused as an invalid app | [other apps](appendices/other-apps.md) |
| Semaphore-managed Terraform state, task stage summaries | paid | stub | [other apps](appendices/other-apps.md) |
| Workflows | paid | not tested | none |

## Identity and credentials

| Capability | Edition | Live result | Guide |
| --- | --- | --- | --- |
| Local users and the four project roles | Community | passed; Guest can read task output and download the project backup | [15](15-identity.md) |
| Key Store (SSH keys, logins, passwords) | Community | passed; values never returned by the API | [6](06-semaphore.md), [15](15-identity.md) |
| Ansible Vault passwords from Key Store | Community | passed in the core verification | [3b](03-controller-el9.md), [15](15-identity.md) |
| TOTP two-factor | Community | caveats: seeds readable by project members; tokens bypass it | [15](15-identity.md) |
| API tokens with expiry | Community | passed; act with the user's current role | [15](15-identity.md), [17](17-api-and-integrations.md) |
| OpenID Connect | Community | passed; no automatic linking to local accounts | [OIDC and LDAP](appendices/identity-providers.md) |
| LDAP | Community | caveats: no certificate verification; an outage blocks all new logins | [OIDC and LDAP](appendices/identity-providers.md) |
| Task JWT for external secret stores | Community | passed with OpenBao | [task identity](appendices/task-identity.md) |
| E-mail one-time codes, custom roles | paid | stub | none |
| Per-template permissions | paid | grant refused | none |
| Native Vault, OpenBao and cloud secret storage | paid | not tested | none |

## Schedules, notifications and task control

| Capability | Edition | Live result | Guide |
| --- | --- | --- | --- |
| Cron and descriptor schedules, `CRON_TZ=` | Community | passed; UTC unless `schedule.timezone` is set | [16](16-semaphore-operations.md) |
| One-time schedules, delete after run | Community | caveats: a UTC offset sent with `run_at` is dropped | [16](16-semaphore-operations.md) |
| Commit-check schedules | Community | passed | [16](16-semaphore-operations.md) |
| E-mail alerts (SMTP, SMTP AUTH) | Community | passed with a local mail catcher; failures only | [16](16-semaphore-operations.md) |
| Slack, Teams, Rocket.Chat, DingTalk, Gotify alerts | Community | caveats: a failed delivery writes the webhook URL into the task log | [16](16-semaphore-operations.md) |
| Telegram alerts, implicit-TLS e-mail | Community | not tested | [16](16-semaphore-operations.md) |
| Global, project and template concurrency limits | Community | passed | [16](16-semaphore-operations.md) |
| Stop and force stop | Community | caveats: processes can outlive the stop; a force-stopped queued task still ran | [16](16-semaphore-operations.md) |
| Raw output and task statistics | Community | passed | [16](16-semaphore-operations.md) |
| Ansible task summary | paid | returns no data | none |
| Maximum task duration | Community | not enforced for tasks on the server | [16](16-semaphore-operations.md) |

## History, audit and portability

| Capability | Edition | Live result | Guide |
| --- | --- | --- | --- |
| Task history, output and statistics | Community | passed | [16](16-semaphore-operations.md) |
| Project activity log | Community | caveats: no logins, user or backup events | [16](16-semaphore-operations.md) |
| syslog output | Community | passed | [16](16-semaphore-operations.md) |
| Activity and task log files | paid | no-op stub | none |
| Task retention and deletion | Community | passed | [maintenance](appendices/maintenance.md) |
| Project export, import, backup and restore | Community | caveats: no secret values, no history | [maintenance](appendices/maintenance.md) |

## API and integrations

| Capability | Edition | Live result | Guide |
| --- | --- | --- | --- |
| REST API with bearer tokens | Community | passed | [17](17-api-and-integrations.md) |
| Swagger UI | Community | passed; its description is from 2.16.14 | [17](17-api-and-integrations.md) |
| Keyset paging of task history | Community | passed | [17](17-api-and-integrations.md) |
| Integrations: token, HMAC, basic, Bitbucket, GitHub | Community | caveats: the receiver answers 204 even when no task started | [17](17-api-and-integrations.md) |
| Integration matchers and extractors | Community | passed | [17](17-api-and-integrations.md) |

## Runners

| Capability | Edition | Live result | Guide |
| --- | --- | --- | --- |
| Global runners with one-time registration | Community | passed | [18](18-runners.md) |
| Runner status, offline wait, disabled runner | Community | passed | [18](18-runners.md) |
| Shared registration token | Community | passed; creates an inactive runner | [18](18-runners.md) |
| `semaphore runner unregister` | Community | fails in 2.19.12; delete the runner instead | [18](18-runners.md) |
| Project runners, runner tags in the UI | paid | stub; tags are reachable only through the API | none |
| Docker and Kubernetes task executors | paid | not tested | none |

## Maintenance

| Capability | Edition | Live result | Guide |
| --- | --- | --- | --- |
| Encryption keyring and `vault rekey` | Community | passed | [maintenance](appendices/maintenance.md) |
| Upgrade with automatic migrations | Community | passed, 2.18.30 to 2.19.12 | [maintenance](appendices/maintenance.md) |
| `semaphore migrate --undo-to` | Community | caveats: the older binary cannot decrypt 2.19 credentials | [maintenance](appendices/maintenance.md) |
| High availability | paid | not tested | none |
