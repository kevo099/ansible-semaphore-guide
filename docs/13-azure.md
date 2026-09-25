# Optional: apply the bootstrap model to Azure

[Back to the guide](../README.md)

This is an extension pattern, not a complete cloud deployment bundled into the
starter lab. The native controller installer creates no Azure resources and
the five practice playbooks assume that targets already exist.

## Goal

Create a Linux VM through Ansible, use cloud-init to install an automation
public key, then validate the guest through the same SSH/Python/sudo path.

## Design your own cloud scope

Use a dedicated resource group and clear ownership tags for disposable tests.
Select a region and VM size that your subscription actually permits. A modest
two-vCPU VM can be a starting point, but check current quota, SKU availability,
image compatibility and the memory required by the workload.

Decide how the controller will reach the guest: an existing approved private
connection, a deliberately configured bastion, or a narrowly scoped alternative.
A private IP alone does not create a route. Avoid adding a public IP or broadly
opening SSH simply to bypass an unresolved network path.

Keep subscription identifiers, actual addresses and authentication material in
your own private configuration. Authenticate with an appropriately scoped
identity and explicitly select the intended subscription. Never bake a cloud
credential into the VM's cloud-init file or give a target the hypervisor/cloud
administrator's private key.

## Organize the automation

Use a separate Python environment for `azure.azcollection` and its required
SDK dependencies; do not casually mix them into the small built-in-only
controller runtime. Pin a tested dependency set for your chosen collection.

A deployment workflow can use native Ansible modules for:

1. The resource group and explicit ownership tags.
2. The network security group and reviewed SSH source scope.
3. The NIC and selected subnet.
4. The Linux VM, its managed disk, bootstrap administrator and cloud-init data.
5. A separate readiness and guest validation phase.
6. Guarded stop/deallocation and eventual cleanup of the exact owned resources.

The [Azure VM module reference](https://docs.ansible.com/projects/ansible/latest/collections/azure/azcollection/azure_rm_virtualmachine_module.html)
documents the current resource options and authentication mechanisms. Confirm
them for your pinned collection version.

## Example cloud-init content

The example below is a template for an Ubuntu 24.04 image. It contains no
working key or password:

```yaml
#cloud-config
ssh_pwauth: false
users:
  - default
  - name: svc_ansible
    shell: /bin/bash
    lock_passwd: true
    ssh_authorized_keys:
      - REPLACE_WITH_YOUR_AUTOMATION_PUBLIC_KEY
packages:
  - python3
  - python3-apt
```

For an AlmaLinux, Rocky Linux or RHEL 9 image, keep the same `users:` section
but replace the package list with the Enterprise Linux prerequisites from
[the access guide](04-access.md#step-3-prepare-a-dedicated-target-account):

```yaml
packages:
  - python3
  - python3-dnf
  - python3-libselinux
```

`python3-apt` does not exist in Enterprise Linux 9 repositories. One unknown
name makes `dnf` reject the whole list, and `cloud-init status` then reports an
error. RHEL also needs working repositories at first boot.

Render the automation **public** key from a controller-side public-key file.
Keep the private key on the controller. Azure also needs the supported
bootstrap administrator/SSH configuration in its VM definition; that is
separate from this additional automation account.

This example does not grant sudo to the new account, and `lock_passwd: true`
leaves it without a password. After the first boot, cloud-init has already
created `svc_ansible` and installed its key, so skip the `scp`, `useradd` and
key `install` commands in
[the access guide's Step 3](04-access.md#step-3-prepare-a-dedicated-target-account).
Through the trusted bootstrap administrator, run `sudo passwd svc_ansible` and
that step's prerequisite checks, then complete
[Step 4](04-access.md#step-4-configure-sudo-and-the-accounts-ssh-policy).
Or design a separate approved secret-delivery mechanism. Do not insert a
reusable plaintext sudo password into custom data.

Use a supported cloud-init image and validate the rendered configuration before
creation. After the first boot, check `cloud-init status --wait` and inspect its
errors privately. Updating a VM's custom-data input is not a general mechanism
for rerunning first-boot setup on an existing machine. Use normal configuration
tasks or a deliberately planned rebuild for later changes. See
[Azure's cloud-init documentation](https://learn.microsoft.com/en-us/azure/virtual-machines/linux/using-cloud-init).

## Validate the outcome

- Verify VM identity, address, image and owned resource set through the cloud
  control plane.
- Obtain the public SSH host key through a trusted console or authenticated
  control-plane mechanism before pinning it.
- Confirm cloud-init completed. After the sudo step above, run
  [the access guide's Step 5](04-access.md#step-5-test-all-three-layers) checks
  against the new host. Before that step, sudo for `svc_ansible` is expected to
  fail.
- Manage a harmless configuration file, repeat the playbook and inspect which
  tasks still report changes.
- Reboot deliberately and repeat guest/application checks.
- Compare the resource set before and after a repeat deployment. A local
  evidence-file refresh is different from a change to a cloud resource.

## Stop compute and retain recovery deliberately

Shutting down Linux from inside the guest can leave Azure compute allocated.
Use the provider's deallocation operation when that is your intended cost
control, and independently check the reported power/allocation state.
Disks and other retained resources can continue to incur charges.

Use a time limit or budget appropriate to your test, and record which resources
remain. Do not apply a generic delete operation to a shared VNet or resource
group. A later “ensure VM present/running” playbook may restart a previously
deallocated VM, so its invocation is an operational action, not a read-only
status check.

## Concept

Cloud-init establishes first-boot access. Ansible manages later desired state.
Cloud lifecycle controls determine whether the machine and its billable
resources remain allocated. Validate each boundary separately.
