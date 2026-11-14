# The setup page

[Back to the guide](../README.md) · [Install the controller at first boot](../docs/first-boot-controller.md)

A small web page that asks where the controller will run, which system it
runs and who its administrator is, and then lists the steps for exactly that
case: each command ready to copy, and what each should show. For a new VM it
also fills in the first-boot file,
[`controller/first-boot/user-data.yaml`](../controller/first-boot/user-data.yaml),
and offers it to copy or download.

The page changes nothing by itself and contacts nothing. What you type stays
in your browser; the answers are kept in the page's address, so a bookmark or
a shared link opens the same steps.

## Open it

- **From a clone of the guide:** open `site/index.html` in a browser.
- **From a web server:** copy the four files of this folder, `index.html`,
  `setup.css`, `plan.js` and `setup.js`, to any folder a web server serves.
  There is nothing to build and nothing to configure, and the page loads
  nothing from another site. Over plain HTTP the copy buttons use the
  browser's older copy command; over HTTPS they use the clipboard directly.

## What it covers

| Where the controller runs | What the steps do |
| --- | --- |
| Proxmox VE | A new VM from a cloud image, with the first-boot file as vendor data |
| Microsoft Azure | A new VM, with the first-boot file as custom data |
| Another hypervisor | A new VM from a cloud image, with the first-boot file on a seed ISO |
| A VM that already exists | The commands of [Stage 1](../docs/stage-1-controller.md), in order, over SSH |

RHEL outside Azure always gets the commands, because a new RHEL VM must be
registered before it can install packages. Every case ends with the same
steps: open Semaphore, change the admin password, add the first machine.

## For maintainers

- [`plan.js`](plan.js) holds everything the page says: the answers'
  checks, the first-boot file and the steps. It also runs in Node, where
  [`tests/test_setup_page.py`](../tests/test_setup_page.py) compares it with
  the guide's files: the embedded first-boot file with
  `controller/first-boot/user-data.yaml`, every command with the scripts and
  pages it comes from, and every link with a heading that exists.
- [`setup.js`](setup.js) is the form and the list. It writes every answer as
  text, never as markup.
- A release changes two places together: `RELEASE` in `plan.js` and
  `release=` in the first-boot file. The tests fail when they differ.
- A new platform is one entry in `PLATFORMS` and one case in `createStep`,
  added once the steps have run there.
