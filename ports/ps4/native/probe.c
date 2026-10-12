/* Arfoxia ShellUI capability probe. Read-only Mono metadata; no UI patches. */
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
typedef struct MonoClass MonoClass;
typedef struct MonoMethod MonoMethod;
extern MonoDomain *mono_get_root_domain(void);
extern MonoThread *mono_thread_attach(MonoDomain *);
extern void mono_thread_detach(MonoThread *);
extern void mono_assembly_foreach(void (*)(MonoAssembly *, void *), void *);
extern MonoImage *mono_assembly_get_image(MonoAssembly *);
extern const char *mono_image_get_name(MonoImage *);
extern MonoClass *mono_class_from_name(MonoImage *, const char *, const char *);
extern MonoMethod *mono_class_get_methods(MonoClass *, void **);
extern char *mono_method_full_name(MonoMethod *, int);
extern void mono_free(void *);

static int descriptor = -1;
static unsigned written, classes;
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
    MonoImage *image = mono_assembly_get_image(value);
    if (!image) return;
    const char *name = mono_image_get_name(image);
    record("ASSEMBLY %s\n", name ? name : "?");
    const char *namespaces[] = {"Sce.PlayStation.PUI.UI2", "Sce.PlayStation.HighLevel.UI2",
        "Sce.PlayStation.PUI", "Sce.Vsh.ShellUI.AppSystem", "System.Threading", NULL};
    const char *types[] = {"UISystem", "Application", "UIContext", "LayerManager", "Scene",
        "Widget", "Panel", "ImageBox", "ImageAsset", "Label", "SynchronizationContext", NULL};
    for (unsigned i=0; namespaces[i]; i++) {
        for (unsigned j=0; types[j]; j++) {
            MonoClass *klass = mono_class_from_name(image, namespaces[i], types[j]);
            if (!klass) continue;
            classes++;
            record("CLASS %s.%s\n", namespaces[i], types[j]);
            void *iterator = NULL;
            MonoMethod *method;
            unsigned count = 0;
            while (count++ < 160 && (method = mono_class_get_methods(klass, &iterator))) {
                char *signature = mono_method_full_name(method, 1);
                record("METHOD %s\n", signature ? signature : "?");
                if (signature) mono_free(signature);
            }
        }
    }
}

int module_start(size_t argc, const void *argv) {
    (void)argc; (void)argv;
    if (ARFOXIA_PS4_PROBE_QUARANTINED) return -4;
    struct arfoxia_process_info info;
    memset(&info, 0, sizeof(info));
    if (arfoxia_sdk(0, NULL) != 0x100 || arfoxia_sdk(4, &info) < 0 ||
        strncmp(info.name, "SceShellUI", sizeof(info.name)) != 0) return -1;
    /* Only an owned diagnostic file, with a size limit. No games/kernel access. */
    descriptor = sceKernelOpen("/user/data/Arfoxia/probe.txt", 0x601, 0600);
    if (descriptor < 0) return -2;
    OrbisKernelSwVersion firmware;
    memset(&firmware, 0, sizeof(firmware));
    firmware.Size = sizeof(firmware);
    int result = sceKernelGetSystemSwVersion(&firmware);
    record("ARFOXIA_PROBE 1\nPROCESS %s PID %d\nFIRMWARE_RC %d VALUE %08x\n",
        info.name, info.pid, result, firmware.Version);
    MonoDomain *domain = mono_get_root_domain();
    MonoThread *thread = domain ? mono_thread_attach(domain) : NULL;
    if (!thread) {
        record("ERROR Mono domain/thread unavailable\n");
    } else {
        mono_assembly_foreach(assembly, NULL);
        record("COMPLETE classes=%u bytes=%u\n", classes, written);
        /* This loader thread may already belong to Mono: do not detach it. */
    }
    sceKernelFsync(descriptor);
    sceKernelClose(descriptor);
    descriptor = -1;
    return 0;
}
int module_stop(size_t argc, const void *argv) { (void)argc; (void)argv; return 0; }
