# Your own playbooks

Put playbooks of your own in this folder, for example `playbooks/site/my-playbook.yml`,
and name that path as the **Playbook Filename** of a template in Semaphore.

The guide's update tool never changes a file it did not put here, so what you
keep in this folder stays yours across releases. A playbook here is one folder
below `playbooks/`, like the guide's own, so it can import the shared checks
the same way:

```yaml
- name: My play
  hosts: lab
  gather_facts: false
  pre_tasks:
    - name: Check scope and supported operating system
      ansible.builtin.import_tasks: ../tasks/preflight.yml
      tags: always
```
