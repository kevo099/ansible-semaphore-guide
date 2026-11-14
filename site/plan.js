/* The setup page's logic, without the page: from the answers to the first-boot file
 * and the numbered steps. It runs in the browser (window.GuidePlan) and in Node
 * (require), where tests/test_setup_page.py checks it against the guide's files. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.GuidePlan = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var RELEASE = 'v1.13.0';
  var REPOSITORY = 'https://github.com/kevo099/ansible-semaphore-guide';
  var FILE_NAME = 'controller-first-boot.yaml';
  // The controller's size from docs/stage-0-plan.md.
  var SIZE = 'at least 2 vCPUs, 4 GiB of memory and a 32 GiB disk';

  // controller/first-boot/user-data.yaml, character for character. A test compares the two.
  /* user-data.yaml: begin */
  var USER_DATA = String.raw`#cloud-config
# Install the guide's controller at the first boot of a new VM: Ubuntu 24.04, or
# RHEL, AlmaLinux or Rocky Linux 9.4 or later. cloud-init installs Git, fetches
# the guide at the release named below as the VM's administrator and runs
# controller/first-boot.sh, which runs the installer and the readiness check.
# About ten minutes after the VM starts, Semaphore is installed and seeded.
#
# Set the four values under "content:" and change nothing else; the setup page,
# site/index.html, fills them in for you.
#
#   release  The guide's release tag to install.
#   admin    The login of the administrator the VM is created with, who will own
#            the guide's folder and the lab folder.
#   expose   tunnel: the UI stays on loopback, for an SSH tunnel. https: nginx
#            also serves it on port 443 of the VM's address.
#   address  With https only: the IP address or DNS name you will browse to,
#            which the certificate names. Empty: the VM's own address, which on
#            a cloud VM behind NAT, as on Azure, is a private one.
#
# Give the file to the new VM's cloud-init: as vendor data where the platform
# writes the user data itself (Proxmox: qm set VMID --cicustom vendor=...), and
# as user data elsewhere (Azure: the Custom data field, or az vm create
# --custom-data). docs/first-boot-controller.md shows each. cloud-init reads it
# at first boot only; on a VM that already exists, follow Stage 1 instead.
#
# The file holds no secret, and the installation prints none: the initial admin
# password is created on the VM and stays in a root-only file there. Do not add
# a write_files:, packages: or runcmd: of your own beside vendor data; it would
# replace this file's.
write_files:
  - path: /etc/ansible-semaphore-guide/first-boot.conf
    owner: root:root
    permissions: "0644"
    content: |
      release=v1.13.0
      admin=REPLACE_WITH_ADMIN_LOGIN
      expose=tunnel
      address=

packages:
  - git

runcmd:
  - - /bin/bash
    - -c
    - |
      # Fetch the guide as the administrator and hand over to its first-boot script.
      set -euo pipefail
      conf=/etc/ansible-semaphore-guide/first-boot.conf
      log=/var/log/ansible-guide-first-boot.log
      origin=https://github.com/kevo099/ansible-semaphore-guide.git
      [[ -e $log ]] || install -m 0600 /dev/null "$log"
      stop() {
        printf 'first-boot: RESULT: STOPPED: %s\n' "$*" | tee -a "$log"
        exit 1
      }
      value() { sed -n "s/^$1=//p" "$conf" | tr -d '\r' | sed 's/[[:space:]]*$//' | tail -n 1; }
      release=$(value release)
      admin=$(value admin)
      [[ $release =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || stop "release= in $conf must be a release tag such as v1.13.0"
      [[ $admin != REPLACE_WITH_ADMIN_LOGIN && $admin =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]] ||
        stop "admin= in $conf must be the login of this VM's administrator; it still holds the placeholder or is empty"
      [[ $admin != root ]] || stop "admin= in $conf must be your own administrator account, not root"
      home=$(getent passwd "$admin" | cut -d: -f6) || home=
      [[ -n $home && -d $home ]] ||
        stop "this VM has no account $admin with a home folder; create the VM with that administrator, or continue by hand with docs/stage-1-controller.md"
      command -v git >/dev/null ||
        stop "Git is not installed, so cloud-init could not install packages. On RHEL, register the system first. Then continue by hand with docs/stage-1-controller.md"
      guide=$home/ansible-semaphore-guide
      if [[ ! -d $guide/.git ]]; then
        runuser -u "$admin" -- env HOME="$home" git clone --quiet --branch "$release" "$origin" "$guide" >>"$log" 2>&1 ||
          stop "could not fetch release $release from $origin; the reason is in $log. Check the VM's outbound HTTPS, then continue by hand with docs/stage-1-controller.md"
      fi
      [[ -f $guide/controller/first-boot.sh ]] ||
        stop "release $release has no controller/first-boot.sh; an installation at first boot needs v1.13.0 or later"
      exec /bin/bash "$guide/controller/first-boot.sh"
`;
  /* user-data.yaml: end */

  var SYSTEMS = {
    ubuntu: {
      label: 'Ubuntu 24.04', installer: 'install-controller.sh', defaultUser: 'ubuntu',
      git: ['sudo apt-get update', 'sudo apt-get install -y git'], enterprise: false
    },
    rhel: {
      label: 'RHEL 9.4 or later', installer: 'install-controller-el9.sh', defaultUser: 'cloud-user',
      git: ['sudo dnf install -y git'], enterprise: true
    },
    almalinux: {
      label: 'AlmaLinux 9.4 or later', installer: 'install-controller-el9.sh', defaultUser: 'almalinux',
      git: ['sudo dnf install -y git'], enterprise: true
    },
    rocky: {
      label: 'Rocky Linux 9.4 or later', installer: 'install-controller-el9.sh', defaultUser: 'rocky',
      git: ['sudo dnf install -y git'], enterprise: true
    }
  };

  // firstBoot: the platform can hand a new VM the first-boot file. checked: what ran, in the
  // words of docs/validation; the page shows it under the step that creates the VM.
  var PLATFORMS = {
    proxmox: {
      label: 'Proxmox VE', hint: 'A new VM from a cloud image, with the file as vendor data.', firstBoot: true,
      checked: 'this file ran as vendor data at a replayed first boot of RHEL 9.8 in the lab, and the qm commands are Stage 3\'s. A new VM made with exactly these commands has not run yet.'
    },
    azure: {
      label: 'Microsoft Azure', hint: 'A new VM, with the file pasted into Custom data.', firstBoot: true,
      checked: 'this file ran as user data at a replayed first boot of Ubuntu 24.04 in the lab. It has not run on Azure yet.'
    },
    seed: {
      label: 'Another hypervisor', hint: 'A new VM from a cloud image, with the file on a small seed ISO.',
      firstBoot: true, checked: 'this file ran from a seed folder at replayed first boots of Ubuntu 24.04 and RHEL 9.8 in the lab. A new VM booted from this ISO has not run yet.'
    },
    existing: {
      label: 'A VM that already exists', hint: 'Any hypervisor or cloud. You paste the commands over SSH.',
      firstBoot: false, checked: ''
    }
  };

  var DEFAULTS = { platform: 'proxmox', system: 'ubuntu', admin: '', expose: 'tunnel', address: '', release: RELEASE };
  var FIELDS = ['platform', 'system', 'admin', 'expose', 'address', 'release'];

  // No wider than controller/first-boot.sh, the command in user-data.yaml and
  // controller/expose-semaphore.sh accept: a value the page lets through is one they take.
  var ADMIN = /^[A-Za-z_][A-Za-z0-9_.-]{0,31}$/;
  var DNS_NAME = /^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$/;
  var RELEASE_NAME = /^v[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$/;

  // An IPv4 address or a DNS name. A name of digits and dots only must be a whole IPv4 address.
  function validAddress(value) {
    if (/^[0-9.]+$/.test(value)) {
      var parts = value.split('.');
      return parts.length === 4 && parts.every(function (part) {
        return /^(0|[1-9][0-9]{0,2})$/.test(part) && Number(part) <= 255;
      });
    }
    return DNS_NAME.test(value);
  }

  function normalize(answers) {
    var result = {};
    FIELDS.forEach(function (field) {
      var value = answers && typeof answers[field] === 'string' ? answers[field].trim() : '';
      result[field] = value || DEFAULTS[field];
    });
    if (!Object.prototype.hasOwnProperty.call(PLATFORMS, result.platform)) { result.platform = DEFAULTS.platform; }
    if (!Object.prototype.hasOwnProperty.call(SYSTEMS, result.system)) { result.system = DEFAULTS.system; }
    if (result.expose !== 'https') { result.expose = 'tunnel'; }
    if (result.expose !== 'https') { result.address = ''; }
    return result;
  }

  // Field name -> what is wrong with it. Empty when the steps can be shown.
  function validate(answers) {
    var a = normalize(answers);
    var errors = {};
    if (!a.admin) {
      errors.admin = 'Enter the login of the VM\'s administrator.';
    } else if (!ADMIN.test(a.admin)) {
      errors.admin = 'A login starts with a letter or an underscore and holds letters, digits, dots, hyphens and underscores only.';
    } else if (a.admin === 'root' || a.admin === 'semaphore') {
      errors.admin = 'Use your own administrator account, not ' + a.admin + ': it will own the lab folder and edit the playbooks.';
    } else if (a.admin === 'svc_ansible') {
      errors.admin = 'svc_ansible is the account Semaphore logs in to the other machines with. Use your own administrator account.';
    } else if (a.platform === 'seed' && method(a).name === 'first-boot' && a.admin !== SYSTEMS[a.system].defaultUser) {
      // The seed ISO of Stage 3 creates no account, so the image's own user is the administrator.
      errors.admin = 'With a seed ISO the administrator is the image\'s own user, which on ' + SYSTEMS[a.system].label +
        ' is ' + SYSTEMS[a.system].defaultUser + '. Enter ' + SYSTEMS[a.system].defaultUser + '.';
    }
    if (a.address && !validAddress(a.address)) {
      errors.address = 'Enter an IPv4 address or a DNS name, without https://, a port or a path.';
    }
    if (!RELEASE_NAME.test(a.release)) {
      errors.release = 'Enter a release tag of the guide, such as ' + RELEASE + '.';
    }
    return errors;
  }

  // 'first-boot' or 'commands', and for 'commands' on a platform that could do the first, why.
  function method(answers) {
    var a = normalize(answers);
    if (!PLATFORMS[a.platform].firstBoot) { return { name: 'commands', reason: '' }; }
    if (a.system === 'rhel' && a.platform !== 'azure') {
      return {
        name: 'commands',
        reason: 'RHEL installs packages only once it is registered, and a new VM is not. Create the VM, ' +
          'register it, then follow these steps over SSH. On Azure, the pay-as-you-go RHEL image needs no ' +
          'registration and can install at first boot.'
      };
    }
    return { name: 'first-boot', reason: '' };
  }

  function replaceOnce(text, from, to) {
    var first = text.indexOf(from);
    if (first === -1 || text.indexOf(from, first + from.length) !== -1) {
      throw new Error('The first-boot file does not have exactly one line "' + from.trim() + '"');
    }
    return text.slice(0, first) + to + text.slice(first + from.length);
  }

  // The first-boot file with the four values filled in. Throws on values validate() refuses.
  function userData(answers) {
    var a = normalize(answers);
    var errors = validate(a);
    var names = Object.keys(errors);
    if (names.length) { throw new Error(errors[names[0]]); }
    var text = USER_DATA;
    text = replaceOnce(text, '\n      release=' + RELEASE + '\n', '\n      release=' + a.release + '\n');
    text = replaceOnce(text, '\n      admin=REPLACE_WITH_ADMIN_LOGIN\n', '\n      admin=' + a.admin + '\n');
    text = replaceOnce(text, '\n      expose=tunnel\n', '\n      expose=' + a.expose + '\n');
    text = replaceOnce(text, '\n      address=\n', '\n      address=' + a.address + '\n');
    return text;
  }

  function doc(a, page, anchor) {
    return REPOSITORY + '/blob/' + a.release + '/docs/' + page + (anchor ? '#' + anchor : '');
  }

  function createStep(a) {
    var system = SYSTEMS[a.system];
    var size = SIZE;
    if (a.platform === 'azure') {
      var ports = a.expose === 'https' ? 'SSH (22) and HTTPS (443)' : 'SSH (22)';
      return {
        id: 'create', title: 'Create the VM in Azure, with the file as custom data', where: 'The Azure portal',
        text: ['Create a virtual machine. The file reaches it through one field on the Advanced tab.'],
        list: [
          'Image: ' + system.label + '. Size: ' + size + '.',
          'Administrator account: SSH public key, with the username ' + a.admin + '.',
          'Inbound ports: ' + ports + ', and under Networking only from your own address.',
          'Advanced tab, Custom data: paste the whole file from step 1.',
          'Review + create.'
        ],
        commands: [],
        expect: 'The deployment succeeds and the VM has an address you can reach over SSH.',
        note: (a.system === 'rhel' ? 'Azure\'s pay-as-you-go RHEL image already has working repositories. ' : '') +
          'With the Azure CLI, az vm create takes the same file as --custom-data.',
        links: [{ text: 'Run the controller in Azure', href: doc(a, 'platform-azure.md', 'optional-do-run-the-controller-in-azure') }]
      };
    }
    if (a.platform === 'proxmox') {
      var commands = [
        'qm create VMID --name controller --ostype l26 --cpu host --cores 2 --memory 4096 \\\n' +
        '  --scsihw virtio-scsi-single --net0 virtio,bridge=vmbr0 \\\n' +
        '  --serial0 socket --vga serial0 --agent enabled=1',
        'qm set VMID --scsi0 STORAGE:0,import-from=/root/IMAGE_FILE',
        'qm set VMID --ide2 STORAGE:cloudinit --boot order=scsi0',
        'qm set VMID --ciuser ' + a.admin + ' --sshkeys /root/ADMIN_KEY.pub --ipconfig0 ip=dhcp',
        'qm resize VMID scsi0 32G'
      ];
      if (system.enterprise) { commands.push('qm set VMID --rng0 source=/dev/urandom'); }
      commands.push('qm set VMID --cicustom "vendor=local:snippets/' + FILE_NAME + '"');
      commands.push('qm start VMID');
      return {
        id: 'create', title: 'Create the VM on Proxmox, with the file as vendor data',
        where: 'The Proxmox node\'s shell, as root',
        text: [
          'Before the first time, allow snippets on the node\'s local storage, and download and check the cloud image ' +
          'of ' + system.label + ' on the node; the two links below show how. Then copy the file from step 1 and your ' +
          'workstation\'s public key to the node, and create the VM. VMID, STORAGE, vmbr0 and IMAGE_FILE are your own values.'
        ],
        list: [],
        commands: [{ label: 'On your workstation', code: 'scp ' + FILE_NAME + ' root@PROXMOX_NODE:/var/lib/vz/snippets/' + FILE_NAME +
          '\nscp ~/.ssh/id_ed25519.pub root@PROXMOX_NODE:/root/ADMIN_KEY.pub' },
          { label: 'On the node', code: commands.join('\n') }],
        expect: 'The VM starts. qm cloudinit dump VMID user shows your administrator ' + a.admin + ' and its key.',
        note: 'Use vendor=, not user=: with user= the administrator and its key from the Cloud-Init panel never reach the VM. ' +
          'For a fixed address, replace ip=dhcp with ip=VM_ADDRESS/PREFIX,gw=GATEWAY_ADDRESS. Proxmox also has a new VM ' +
          'install every pending update at its first boot, before the controller; qm set VMID --ciupgrade 0 turns that off.',
        links: [{ text: 'Allow snippets on a storage', href: doc(a, 'platform-proxmox.md', 'do-enable-snippets-on-a-storage') },
          { text: 'Build a VM from a cloud image', href: doc(a, 'platform-proxmox.md', 'do-build-a-vm-from-a-cloud-image') },
          { text: 'Stage 3: each of these commands explained', href: doc(a, 'stage-3-new-vms-cloud-init.md', 'do-on-proxmox-attach-the-file-to-a-new-vm') }]
      };
    }
    return {
      id: 'create', title: 'Build a seed ISO with the file, and boot the new VM with it',
      where: 'Any Linux machine that holds the file from step 1',
      text: [
        'cloud-init reads a small ISO with the volume label cidata. It holds the VM\'s name and your public key as ' +
        'user data, and the file from step 1, unchanged, as vendor data. Replace the key line with your own. ' +
        'The key belongs to the image\'s default user, which on ' + system.label + ' is ' + system.defaultUser + '.'
      ],
      list: [],
      commands: [{
        label: '', code:
          'mkdir -p ~/seed-controller\n' +
          'cd ~/seed-controller\n' +
          'cp ~/' + FILE_NAME + ' vendor-data\n' +
          'printf \'instance-id: %s\\nlocal-hostname: %s\\n\' controller-1 controller > meta-data\n' +
          'cat > user-data <<\'USERDATA\'\n' +
          '#cloud-config\n' +
          'hostname: controller\n' +
          'fqdn: controller.lab.example\n' +
          'ssh_authorized_keys:\n' +
          '  - ssh-ed25519 AAAA... you@workstation\n' +
          'USERDATA\n' +
          'xorriso -as mkisofs -output ~/seed-controller.iso -volid cidata -joliet -rock user-data meta-data vendor-data'
      }],
      expect: 'seed-controller.iso exists. Attach it to the new VM as a CD/DVD drive before its first boot, give the VM ' +
        size + ', and start it.',
      note: 'This seed creates no account of its own, so the administrator is the image\'s own user, ' + system.defaultUser + '.',
      links: [{ text: 'Stage 3: the seed ISO explained', href: doc(a, 'stage-3-new-vms-cloud-init.md', 'do-on-another-hypervisor-build-a-nocloud-seed') }]
    };
  }

  function openSteps(a) {
    var steps = [];
    if (a.expose === 'https') {
      steps.push({
        id: 'open', title: 'Open Semaphore over HTTPS', where: 'The controller, then your browser',
        text: [
          'The installer printed the address and the fingerprint of its self-signed certificate. Read both, browse to ' +
          'the address, and accept the browser\'s warning only when it shows the same fingerprint.'
        ],
        list: [],
        commands: [{ label: '', code: a.method === 'first-boot' ?
          'sudo grep -E \'Semaphore UI|fingerprint\' /var/log/ansible-guide-first-boot.log' :
          'sudo bash controller/expose-semaphore.sh --mode https' + (a.address ? ' --address ' + a.address : '') }],
        expect: 'Semaphore UI: https://' + (a.address || 'CONTROLLER_ADDRESS') + '/ and one line with the certificate\'s SHA-256 fingerprint. The login page opens.',
        note: 'A firewall in front of the VM is yours to open, for port 443 and only from your own address.',
        links: [{ text: 'Browser access', href: doc(a, 'appendices/browser-access.md', 'https-on-the-vms-address') }]
      });
    } else {
      steps.push({
        id: 'open', title: 'Open Semaphore through an SSH tunnel', where: 'Your workstation',
        text: ['Keep this command running while you use the UI, and browse to http://127.0.0.1:8088/. It prints nothing while the tunnel is open.'],
        list: [],
        commands: [{ label: '', code: 'ssh -N -o ExitOnForwardFailure=yes \\\n  -L 127.0.0.1:8088:127.0.0.1:3000 \\\n  ' + a.admin + '@CONTROLLER_ADDRESS' }],
        expect: 'The Semaphore login page at http://127.0.0.1:8088/.',
        note: '',
        links: [{ text: 'Stage 1: open Semaphore', href: doc(a, 'stage-1-controller.md', 'do-open-semaphore') }]
      });
    }
    steps.push({
      id: 'password', title: 'Sign in and change the password', where: 'The controller, as ' + a.admin,
      text: [
        'Read the initial password, log in as admin with it, then change the password in the UI and keep the new one ' +
        'in your password manager. Paste it nowhere else.'
      ],
      list: [],
      commands: [{ label: '', code: 'sudo cat /etc/semaphore/initial-admin-password' }],
      expect: 'The project Ansible Automation, with the tabs Baseline, Patching, four STIG tabs, Operations and Examples.',
      note: '', links: []
    });
    steps.push({
      id: 'machine', title: 'Add your first machine',
      where: 'The controller, as ' + a.admin + ', in the guide\'s folder, without sudo',
      text: [
        'ADMIN@MACHINE_ADDRESS is the administrator and the address of a Linux machine the controller can reach over ' +
        'SSH. The first command asks for your sudo password, for one shared sudo password that the automation account ' +
        'gets on your machines, and shows the machine\'s host key for you to compare. The second gives Semaphore that ' +
        'shared password. Then run Ping on the Baseline tab.'
      ],
      list: [],
      commands: [{ label: '', code: 'cd ~/ansible-semaphore-guide\nbash controller/onboard-target.sh ADMIN@MACHINE_ADDRESS\nsudo python3.12 controller/lab-sudo.py' }],
      expect: 'Prepared and in the inventory: ADMIN@MACHINE_ADDRESS, and a Ping task that ends with success.',
      note: '',
      links: [{ text: 'Stage 2: machines that exist', href: doc(a, 'stage-2-existing-machines.md', 'do-onboard-it-in-one-command-from-the-controller') },
        { text: 'Stage 4: the sudo password and the first job', href: doc(a, 'stage-4-add-target-first-job.md', 'do-give-semaphore-the-sudo-password') }]
    });
    return steps;
  }

  // The numbered steps for these answers. Throws on values validate() refuses.
  function steps(answers) {
    var a = normalize(answers);
    var errors = validate(a);
    var names = Object.keys(errors);
    if (names.length) { throw new Error(errors[names[0]]); }
    var chosen = method(a);
    a.method = chosen.name;
    var system = SYSTEMS[a.system];
    var result = [];
    if (chosen.name === 'first-boot') {
      result.push({
        id: 'file', title: 'Save the first-boot file', where: 'Your workstation',
        text: [
          'This file installs the controller when the new VM starts for the first time: it installs Git, fetches the ' +
          'guide at release ' + a.release + ' as ' + a.admin + ', and runs the installer. It holds no secret. Save it as ' +
          FILE_NAME + '.'
        ],
        list: [], commands: [], file: { name: FILE_NAME, content: userData(a) },
        expect: 'A file of about 4 kB that starts with #cloud-config.',
        note: '',
        links: [{ text: 'What the file does', href: doc(a, 'first-boot-controller.md', '') }]
      });
      var create = createStep(a);
      create.checked = PLATFORMS[a.platform].checked;
      result.push(create);
      result.push({
        id: 'wait', title: 'Wait for the first boot to finish', where: 'The new VM, over SSH as ' + a.admin,
        text: [
          'The installation takes several minutes; allow ten. The first command waits until cloud-init is done; the ' +
          'second shows how it ended. Keep the sudo: without it the first command waits forever on Enterprise Linux 9.8.'
        ],
        list: [],
        commands: [{ label: '', code: 'sudo cloud-init status --wait\nsudo tail -n 4 /var/log/ansible-guide-first-boot.log' }],
        expect: 'status: done, and first-boot: RESULT: OK. After RESULT: STOPPED: comes the reason and what to do.',
        note: 'If this workstation has not logged in to the VM before, compare the host-key fingerprint SSH shows with the VM\'s console first.',
        links: [{ text: 'When the first boot stops', href: doc(a, 'first-boot-controller.md', 'when-it-stops') }]
      });
    } else {
      result.push({
        id: 'login', title: 'Log in to the VM', where: 'Your workstation',
        text: [
          'The VM runs ' + system.label + ' with ' + SIZE +
          ', and nothing else is installed on it.' + (chosen.reason ? ' ' + chosen.reason : '')
        ],
        list: [],
        commands: [{ label: '', code: 'ssh ' + a.admin + '@CONTROLLER_ADDRESS' }],
        expect: 'A shell on the VM as ' + a.admin + ', who can use sudo.',
        note: a.system === 'rhel' ? 'RHEL must be registered, with BaseOS and AppStream enabled, before the next step.' : '',
        links: [{ text: 'Stage 0: plan and create the VM', href: doc(a, 'stage-0-plan.md', 'do-create-the-controller-vm') }]
      });
      result.push({
        id: 'guide', title: 'Install Git and fetch the guide', where: 'The controller, as ' + a.admin,
        text: ['~/ansible-semaphore-guide becomes the guide\'s folder. Every later command that starts with controller/ runs from it.'],
        list: [],
        commands: [{ label: '', code: system.git.concat([
          'git clone --branch ' + a.release + ' ' + REPOSITORY + '.git ~/ansible-semaphore-guide',
          'cd ~/ansible-semaphore-guide']).join('\n') }],
        expect: 'Git says the checkout is a "detached HEAD", which is expected for a release tag.',
        note: '',
        links: [{ text: 'Stage 1: get the guide onto the controller', href: doc(a, 'stage-1-controller.md', 'do-get-the-guide-onto-the-controller') }]
      });
      var options = a.expose === 'https' ? ' --expose https' + (a.address ? ' --address ' + a.address : '') : '';
      result.push({
        id: 'plan', title: 'Read the installer\'s plan', where: 'The controller, in the guide\'s folder',
        text: ['Without --apply the installer only prints what it would do.'],
        list: [],
        commands: [{ label: '', code: 'sudo bash controller/' + system.installer }],
        expect: 'A list that starts with Plan: and changes nothing.',
        note: '', links: []
      });
      result.push({
        id: 'install', title: 'Install the controller', where: 'The controller, in the guide\'s folder',
        text: ['This installs PostgreSQL, Semaphore and Ansible and seeds the project. It takes several minutes and prints no secret.'],
        list: [],
        commands: [{ label: '', code: 'sudo bash controller/' + system.installer + ' --apply' + options }],
        expect: 'Controller installed and seeded.',
        note: 'The installer does not run twice on one VM. If it stops, the message says why.',
        links: [{ text: 'Stage 1: install with the installer', href: doc(a, 'stage-1-controller.md', 'do-install-with-the-installer') },
          { text: 'When it fails', href: doc(a, 'stage-1-controller.md', 'when-it-fails') }]
      });
      result.push({
        id: 'check', title: 'Check that the controller is ready', where: 'The controller, in the guide\'s folder',
        text: ['The readiness check reads the services, ports and files the installer made.'],
        list: [],
        commands: [{ label: '', code: 'sudo python3.12 controller/check-controller.py' }],
        expect: '"passed": true',
        note: '',
        links: [{ text: 'Stage 1: controller readiness', href: doc(a, 'stage-1-controller.md', 'check-controller-readiness') }]
      });
    }
    return result.concat(openSteps(a));
  }

  // The answers as a query string for the address bar, and back. Unknown names are ignored.
  function encode(answers) {
    var a = normalize(answers);
    return FIELDS.filter(function (field) { return a[field] && a[field] !== DEFAULTS[field]; })
      .map(function (field) { return field + '=' + encodeURIComponent(a[field]); }).join('&');
  }

  function decode(text) {
    var answers = {};
    String(text || '').replace(/^[#?]/, '').split('&').forEach(function (pair) {
      var at = pair.indexOf('=');
      if (at === -1) { return; }
      var name = pair.slice(0, at);
      if (FIELDS.indexOf(name) === -1) { return; }
      try { answers[name] = decodeURIComponent(pair.slice(at + 1)); } catch (error) { /* a broken escape: ignore the value */ }
    });
    return normalize(answers);
  }

  return {
    RELEASE: RELEASE, REPOSITORY: REPOSITORY, FILE_NAME: FILE_NAME, USER_DATA: USER_DATA,
    SYSTEMS: SYSTEMS, PLATFORMS: PLATFORMS, DEFAULTS: DEFAULTS,
    normalize: normalize, validate: validate, method: method, userData: userData, steps: steps,
    encode: encode, decode: decode
  };
});
