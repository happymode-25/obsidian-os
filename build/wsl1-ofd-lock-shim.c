/*
 * wsl1-ofd-lock-shim.c - supply the open-file-description lock WSL1 lacks.
 *
 * WHY THIS EXISTS
 * ---------------
 * WSL1's kernel emulation does not implement open-file-description locks.
 * Measured, not assumed:
 *
 *   fcntl(fd, F_OFD_SETLK,  &fl)  -> EINVAL   on wslfs AND on tmpfs
 *   fcntl(fd, F_SETLK,    &fl)    -> OK
 *   flock(fd, LOCK_EX)            -> OK
 *
 * It is a missing kernel feature, not a filesystem problem: no mount
 * arrangement changes the result. systemd takes an OFD lock on /etc/passwd,
 * so on WSL1 every systemd package fails to configure with
 *
 *   Failed to take /etc/passwd lock: Invalid argument
 *
 * and the build cannot produce an image.
 *
 * WHY THIS OVERRIDES FUNCTIONS RATHER THAN fcntl
 * ----------------------------------------------
 * The obvious approach - preload a fcntl that rewrites F_OFD_* to F_* - was
 * built and tested. It does not work, and the reason is worth recording:
 * systemd-sysusers imports no fcntl symbol at all. It imports
 * take_etc_passwd_lock, and the fcntl call is made from inside
 * libsystemd-shared. A preloaded fcntl is never consulted for it. Verified by
 * strace (F_OFD_SETLKW still returned EINVAL with the fcntl shim loaded) and by
 * the absence of any interposition message.
 *
 * The fcntl translation is retained below as a secondary path for any binary
 * that does call libc's fcntl directly, but the function overrides are what
 * make this work.
 *
 * SAFETY
 * ------
 * Every function replaced here is a *lock acquisition*, not the write that
 * follows it. Returning success tells the caller "you hold the lock", after
 * which it performs the same writes it would on a working kernel. The writes
 * are therefore genuine; only the mutual exclusion is waived.
 *
 * That is sound here because the exclusion exists to stop two processes
 * editing /etc/passwd at once, and during package configuration:
 *   - dpkg holds the exclusive dpkg database lock, so no other package
 *     maintainer script is running;
 *   - the chroot is private to this build; no live system is writing it.
 * There is no second writer to exclude. The failure mode if this reasoning
 * were wrong would be a lost update, not a corrupted system.
 *
 * This is a BUILD-HOST compatibility shim. It is installed into the chroot,
 * active only while dpkg configures packages, and removed before the image is
 * sealed. The shipped image contains stock Debian binaries and none of this;
 * the kernel it boots implements F_OFD_SETLK natively.
 *
 * Not for general use. Guarded by a runtime probe in build-iso.sh: on a host
 * with working OFD locks this file is never compiled or installed.
 */

#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stddef.h>

/* ABI-stable since Linux 3.15; not exposed by every libc header. */
#ifndef F_OFD_GETLK
#define F_OFD_GETLK 36
#endif
#ifndef F_OFD_SETLK
#define F_OFD_SETLK 37
#endif
#ifndef F_OFD_SETLKW
#define F_OFD_SETLKW 38
#endif

typedef int (*fn_t)(int, int, ...);

static int translate_ofd(int cmd, int *out)
{
    if (cmd == F_OFD_SETLK)  { *out = F_SETLK;  return 1; }
    if (cmd == F_OFD_SETLKW) { *out = F_SETLKW; return 1; }
    if (cmd == F_OFD_GETLK)  { *out = F_GETLK;  return 1; }
    return 0;
}

/*
 * Secondary path only. Kept because a binary that calls fcntl() from its own
 * code (rather than from libsystemd-shared) would be covered by this, and it
 * is exercised by scripts/test-ofd-shim.sh. See the header comment for why
 * this alone is insufficient.
 */
int fcntl(int fd, int cmd, ...)
{
    static fn_t real;
    int t; va_list ap; void *arg;

    if (real == NULL)
        real = (fn_t)dlsym(RTLD_NEXT, "fcntl");
    if (translate_ofd(cmd, &t)) {
        va_start(ap, cmd);
        arg = va_arg(ap, void *);
        va_end(ap);
        return real(fd, t, arg);
    }
    return real(fd, cmd);   /* two-arg form: read no va_arg */
}

/* systemd is built with -D_FILE_OFFSET_BITS=64, so some callers bind here. */
int fcntl64(int fd, int cmd, ...)
{
    static fn_t real;
    int t; va_list ap; void *arg;

    if (real == NULL)
        real = (fn_t)dlsym(RTLD_NEXT, "fcntl64");
    if (translate_ofd(cmd, &t)) {
        va_start(ap, cmd);
        arg = va_arg(ap, void *);
        va_end(ap);
        return real(fd, t, arg);
    }
    return real(fd, cmd);
}

/*
 * The lock helpers themselves, in libsystemd-shared. `op` is deliberately
 * unnamed: these overrides ignore it and unconditionally report success,
 * because the only correct answer for both LOCK_EX and LOCK_UN on a host that
 * cannot lock at all is "fine". The writes the caller performs afterwards are
 * the real ones.
 *
 * Declared with int rather than systemd's Operation enum for ABI
 * compatibility; the argument is not read.
 */
int take_etc_passwd_lock(int op)  { (void) op; return 0; }
int take_etc_shadow_lock(int op)  { (void) op; return 0; }
int take_etc_gshadow_lock(int op) { (void) op; return 0; }
int take_etc_group_lock(int op)   { (void) op; return 0; }
int take_etc_subuid_lock(int op)  { (void) op; return 0; }
int take_etc_subgid_lock(int op)  { (void) op; return 0; }
