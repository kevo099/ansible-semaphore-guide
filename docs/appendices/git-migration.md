# Appendix: move the seeded lab folder to a Git repository

[Back to the Enterprise Linux controller](../03-controller-el9.md) · [Git and VS Code](../07-git-and-vscode.md)

## Goal

Publish the seeded controller's playbooks to a private Git repository without
publishing its inventory, Vault files or history you did not mean to share,
and switch templates to it one at a time.

This applies to the [Enterprise Linux seeded controller](../03-controller-el9.md),
whose **Local lab folder** repository is `/opt/ansible-lab`. The
[Git chapter](../07-git-and-vscode.md) explains the difference between edited,
committed, pushed and executed code; read it first.

## Do: stop tracking private files

**Where: the controller, as the lab folder's owner.**

Semaphore reads the **Local lab folder** straight from its working tree,
uncommitted edits included. A template switched to a remote repository runs
only what you committed and pushed, so review and commit before you switch.

The folder's `.gitignore` keeps `inventories/`, `host_vars/` and `group_vars/`
out of Git, so target addresses and Vault files stay on the controller. A
folder installed with v1.1.0 of this guide or earlier has no such file, and
its first commit tracks `inventories/lab.ini`. If `git ls-files inventories`
prints anything, stop tracking that folder first. The files stay on disk,
where Semaphore keeps reading them. Git records you as the author, so set
`git config --global user.name` and `user.email` first if you have not:

```bash
cd /opt/ansible-lab
printf '%s\n' 'inventories/' 'host_vars/' 'group_vars/' >> .gitignore
git rm -r -q --cached inventories
git add .gitignore
git commit -m 'Keep the local inventory and Vault files out of Git'
```

## Do: review what a push would publish

```bash
cd /opt/ansible-lab
git status --short
git ls-files
git log --name-only --format= | sort -u
git log --oneline -- inventories/
```

Commit your playbook changes by name, as in
[the Git chapter](../07-git-and-vscode.md#do-create-your-own-working-copy);
`.gitignore` is not a secret detector. `git ls-files` shows only the current
files, but a push also publishes every earlier commit, including files you
later deleted. The third command lists every path in that history; each must
be something you intend to publish, apart from the installer's empty
`inventories/lab.ini` in an older folder. The last command must print nothing,
or only the installer's first commit and the commit above. Any other commit
touched the inventory and can hold real target addresses or Vault data.

## Do: publish only the current files when history is private

If the last command printed any other commit, or the path list shows anything
else private, publish only the current files. A new history still contains
every file Git tracks now, so first stop tracking any private file that
`git ls-files` lists: run
`git rm --cached FILE`, add its path to `.gitignore` and commit, as the block
above does for `inventories/`. Then give the current files a new one-commit
`main` and keep the old history on the controller under another name that you
never push:

```bash
cd /opt/ansible-lab
git checkout --orphan publish main
git commit -m 'Lab playbooks for the private repository'
git branch -m main local-history
git branch -m publish main
git log --oneline -- inventories/
```

The last command now prints nothing, and the working tree, `inventories/`
included, is unchanged. Push only to a **private** repository:

```bash
git remote add origin YOUR_PRIVATE_REPOSITORY_URL
git push -u origin main
```

## Do: point templates at the repository

Add a second Semaphore repository object with the repository's HTTPS URL
and its own read-only access token, stored as a **Login with password** key:
the user name your Git host expects for tokens in **Username** and the token
in **Password**. Avoid an SSH URL with an SSH key: Semaphore 2.19.12 clones
over SSH with host-key checking turned off (`StrictHostKeyChecking=no`,
`UserKnownHostsFile=/dev/null`), so it would not verify the Git host. Switch
one template at a time. The inventory, keys and variable groups stay as they
are: **Lab inventory file** stays bound to the **Local lab folder**
repository, so Semaphore keeps reading `/opt/ansible-lab/inventories/lab.ini`
and its `host_vars` on the controller. Keep that folder and repository object,
and keep adding targets there.

**Check:** a template switched to the new repository runs Ping and shows a
clone step in its log. In the pushed repository, `git log --oneline --
inventories/` prints nothing after a new one-commit history, or only the
installer's first commit and the untracking commit when you kept the reviewed
history.

## Concept

A local folder is a practice convenience: Semaphore runs whatever is in its
working tree, reviewed or not. A remote repository makes a task run only what
you committed and pushed, which is what makes review meaningful.
