# Contributing to Obsidian OS

Thanks for your interest in helping complete Obsidian OS! This project is a hardened Debian-based Linux distribution. 

## Current Status

**Task 1.7 (Hardened Kernel Integration)** is in progress but blocked by local hardware constraints. The kernel build infrastructure is mostly complete, but finishing the build requires a more powerful machine or more time.

### What's Done
- Hardened kernel build scripts (scripts/build-kernel.sh) with Debian trixie kernel source + hardened.config fragment
- Kernel built with LOCALVERSION=-obsidian-h for identification
- Build infrastructure with resumable builds and autopilot for continuous building
- ISO build wiring for --kernel-deb flag
- Boot marker system for strict validation
- All build tooling and automation

### What's Left (for Task 1.7)
1. Complete the kernel debian package build (linux-image-*.deb, headers, etc.)
2. Build the ISO with --kernel-deb pointing to the built kernel packages
3. Run strict boot gate tests to verify the hardened kernel boots correctly
4. Flip kernel-identity: obsidian-hardened to required in 	ests/boot-markers.conf
5. Commit evidence and complete the task

## How You Can Help

### Option 1: Complete the Kernel Build
The kernel needs to be built on a Linux system with:
- At least 16GB RAM, preferably 32GB+
- ~100GB+ free disk space
- Multi-core CPU (8+ cores recommended)
- Debian/Ubuntu-based build environment

`ash
# In a WSL/Linux environment
cd /path/to/obsidian-os
./scripts/build-kernel.sh
`

The build takes several hours depending on hardware. The packages will be output to uild/kernel-out/.

### Option 2: Build the ISO
Once kernel debs are available:

`ash
./launch-kernel-iso.sh daily
`

Or manually:
`ash
./build/build-iso.sh --flavor daily --suite trixie --kernel-deb /root/kernel-out/obsidian-linux-image-*.deb
`

### Option 3: Test & Validate
Run the boot tests against the generated ISO:
`ash
# Windows
./tests/boottest-win.ps1 -Iso build/out/obsidian-daily-trixie-amd64.iso -Flavor daily
`

## Development Setup

1. Fork the repo
2. Clone your fork
3. Follow the build instructions in docs/
4. Make your changes
5. Submit a pull request

## Key Files
- scripts/build-kernel.sh - Kernel build automation
- overlays/common/etc/obsidian/kernel/hardened.config - Hardening configuration
- uild/build-iso.sh - ISO build with kernel deb support
- 	ests/boot-markers.conf - Boot validation markers
- overlays/common/usr/local/sbin/obsidian-boot-report - Kernel identity detection

## Notes
- The build uses a persistent tree at /root/kernel-build for resumability
- Watch for debhelper dependency (we just fixed this!)
- The kernel version is Debian trixie 6.12.x with LOCALVERSION=-obsidian-h

Happy hacking! If you have questions, please open an issue.
