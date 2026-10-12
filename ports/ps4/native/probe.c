/* Quarantined inventory only. Type/method discovery is now done OFFLINE. */
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <stdint.h>
#include <orbis/libkernel.h>
#include "goldhen_abi.h"

typedef struct MonoDomain MonoDomain;
typedef struct MonoThread MonoThread;
typedef struct MonoAssembly MonoAssembly;
typedef struct MonoImage MonoImage;
extern MonoDomain *mono_get_root_domain(void);
extern MonoThread *mono_thread_attach(MonoDomain *);
extern void mono_assembly_foreach(void (*)(MonoAssembly *, void *), void *);
extern MonoImage *mono_assembly_get_image(MonoAssembly *);
extern const char *mono_image_get_name(MonoImage *);

static int descriptor = -1;
static unsigned written, assemblies;
static void record(const char *format, ...) {
    if (descriptor < 0 || written >= 128*1024) return;
    char line[1024];
    va_list args;
    va_start(args, format);
    int n = vsnprintf(line, sizeof(line), format, args);
    va_end(args);
    if (n < 0) return;
    if (n >= (int)sizeof(line)) n = sizeof(line)-1;
    if (sceKernelWrite(descriptor, line, (size_t)n) == (size_t)n) written += (unsigned)n;
}

static void assembly(MonoAssembly *value, void *unused) {
    (void)unused;
    if (assemblies >= 512) return;
    assemblies++;
    record("PHASE assembly_image %u\n", assemblies);
    sceKernelFsync(descriptor);
    MonoImage *image = mono_assembly_get_image(value);
    if (!image) return;
    record("PHASE assembly_name %u\n", assemblies);
    sceKernelFsync(descriptor);
    const char *name = mono_image_get_name(image);
    record("ASSEMBLY %.256s\n", name ? name : "?");
    /* No class resolution, AOT cache lookup, method loading or invocation. */
}

int module_start(size_t argc, const void *argv) {
    (void)argc; (void)argv;
    if (ARFOXIA_PS4_PROBE_QUARANTINED) return -4;
    struct arfoxia_process_info info;
    memset(&info, 0, sizeof(info));
    if (arfoxia_sdk(0, NULL) != 0x100 || arfoxia_sdk(4, &info) < 0 ||
        strncmp(info.name, "SceShellUI", sizeof(info.name)) != 0) return -1;
    /* Still quarantined: offline redesign does not establish console safety. */
    descriptor = sceKernelOpen("/user/data/Arfoxia/probe.txt", 0x601, 0600);
    if (descriptor < 0) return -2;
    OrbisKernelSwVersion firmware;
    memset(&firmware, 0, sizeof(firmware));
    firmware.Size = sizeof(firmware);
    int result = sceKernelGetSystemSwVersion(&firmware);
    record("ARFOXIA_INVENTORY 2\nPROCESS %s PID %d\nFIRMWARE_RC %d VALUE %08x\n",
        info.name, info.pid, result, firmware.Version);
    record("PHASE root_domain\n");
    sceKernelFsync(descriptor);
    MonoDomain *domain = mono_get_root_domain();
    record("PHASE thread_attach\n");
    sceKernelFsync(descriptor);
    MonoThread *thread = domain ? mono_thread_attach(domain) : NULL;
    if (!thread) {
        record("ERROR Mono domain/thread unavailable\n");
    } else {
        record("PHASE assembly_foreach\n");
        sceKernelFsync(descriptor);
        mono_assembly_foreach(assembly, NULL);
        record("COMPLETE assemblies=%u bytes=%u limit=%u\n", assemblies, written,
            assemblies == 512);
        /* This loader thread may already belong to Mono: do not detach it. */
    }
    sceKernelFsync(descriptor);
    sceKernelClose(descriptor);
    descriptor = -1;
    return 0;
}
int module_stop(size_t argc, const void *argv) { (void)argc; (void)argv; return 0; }
