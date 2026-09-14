# 12. Progress from examples to independent automation

[Previous: troubleshooting](11-troubleshooting.md) · [Optional: Azure](13-azure.md)

## Goal

Understand the setup well enough to write and troubleshoot your own playbooks,
then repeat the work on clean targets.

## Stage 1: a worked example

Complete the manual controller and SSH walkthrough once. For each layer,
explain its purpose before moving on:

- What runs on the controller, and what runs on the target?
- Which credential authenticates SSH, and which one permits sudo?
- Which file tells Ansible about the hosts?
- What is different between a terminal run and a Semaphore run?
- What does a green check-mode result leave untested?

Run the baseline lesson and inspect the actual banner/service. Follow it with
a repeat run and a deliberate drift repair.

## Stage 2: complete small changes

Use the examples as scaffolding:

1. Add one ordinary `lab_` account and predict its tasks.
2. Change only the web page text. Explain why nginx need not restart.
3. Change a valid nginx configuration setting. Observe the handler.
4. Add an assertion that the generated page contains your exact message.
5. Create separate variables for Ubuntu and Alma service names.
6. Make one target unavailable, observe the failure, restore it and retry.

Before every apply, name the files or resources you expect to change. After
the run, inspect the target independently rather than relying only on the recap.

## Stage 3: write your own role

In your private working repository, create a role for a small service. Separate
defaults, tasks, handlers and templates. Use facts and variables to support
both target OSes. Avoid `shell` where a purpose-built module expresses the
desired state more clearly.

Your completion criteria:

- The playbook selects only its intended inventory group.
- Syntax and supported previews pass.
- The first apply reaches the required state.
- The immediate repeat makes no unnecessary configuration changes.
- Invalid input fails before making the corresponding change.
- A service configuration is validated before activation.
- A clean second target reaches the same intended state.

## Stage 4: an independent mini-project

Start from a clean target and a short requirement, without copying the starter
playbook: create a team group and users, install a service, deploy a host-specific
template, enable the service and verify its response. Supply secrets through
a private mechanism. Put the code in Git and run the reviewed commit through
Semaphore after the CLI path works.

Add a documented maintenance operation and a recovery drill. Explain exactly
what your backup includes and demonstrate an authenticated task after recovery.
Keep the exercise small enough that you can understand every change.

## Relationship to RHCE/EX294

The Ansible-focused exam is EX294, currently listed as **Red Hat Certified
Advanced System Administrator in Ansible**. It contributes to the **RHCE in
Ansible** path. Confirm the requirements and objectives for the version you
book using [Red Hat's certification catalog](https://www.redhat.com/en/services/certifications)
and [EX294 objectives](https://www.redhat.com/en/services/training/ex294-red-hat-certified-engineer-rhce-exam-red-hat-enterprise-linux).

| Skill area | Practice here | Additional work |
| --- | --- | --- |
| Inventories, modules and configuration | CLI setup and five lessons | Build inventories/configuration independently. |
| Managed-node access and privilege escalation | SSH/sudo bootstrap | Recover from incorrect account or trust configuration. |
| Variables, facts, loops and conditions | Users, OS mapping and templates | Write your own conditional and error-handling logic. |
| Roles and collections | Role mini-project | Install and use relevant collections and reusable roles. |
| Linux administration through Ansible | Packages, accounts, services and files | Add storage, filesystems, firewall, archives and scheduling exercises. |
| Templates and protected data | Web template and optional Vault | Practice Vault and per-host data in a private repository. |
| Git, VS Code and execution tools | Editing and revision workflow | Practice `ansible-navigator` and development containers for the booked exam version. |

EX294 evaluates practical automation, including applying candidate playbooks to
fresh systems. Replaying your own work on a clean target is valuable practice.
Semaphore is not a listed exam objective. It is useful operational experience
around the Ansible core; it does not substitute for independent playbook work.

This repository is not official exam material, a full objective-coverage claim
or an exam simulator. The native controller path does not install the exam's
development-container environment. Add that separately using the applicable
Red Hat tooling and version guidance.

## Concept

Familiarity comes from seeing the pieces work. Proficiency comes from choosing
the right pieces, diagnosing failures and reproducing the result yourself.
