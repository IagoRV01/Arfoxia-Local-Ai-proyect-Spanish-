/* NEW, one-callback experiment. No widget creation, patches, hooks or renderer.
 * Kept disabled in all normal builds. Host/AOT tests are not PS4 validation.
 */
#include <stddef.h>
#ifndef ARFOXIA_PS4_DISPATCH_PROBE_ENABLED
#define ARFOXIA_PS4_DISPATCH_PROBE_ENABLED 0
#endif

#if !ARFOXIA_PS4_DISPATCH_PROBE_ENABLED
int module_start(size_t argc, const void *argv) { (void)argc; (void)argv; return -4; }
int module_stop(size_t argc, const void *argv) { (void)argc; (void)argv; return 0; }
#else
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <stdatomic.h>
#include <orbis/libkernel.h>
#include "goldhen_abi.h"
#include "dispatch_contract.h"
#include "dispatch_profile.h"
#if !ARFOXIA_DISPATCH_PROFILE_PRESENT
#error A private validated dispatch profile is required
#endif

typedef struct MonoDomain MonoDomain;
typedef struct MonoAssembly MonoAssembly;
typedef struct MonoAssemblyName MonoAssemblyName;
typedef struct MonoImage MonoImage;
typedef struct MonoClass MonoClass;
typedef struct MonoMethod MonoMethod;
typedef struct MonoObject MonoObject;
typedef struct MonoThread MonoThread;
extern MonoDomain *mono_get_root_domain(void);
extern MonoThread *mono_thread_attach(MonoDomain *);
extern MonoImage *mono_get_corlib(void);
extern MonoAssemblyName *mono_assembly_name_new(const char *);
extern void mono_assembly_name_free(MonoAssemblyName *);
extern MonoAssembly *mono_assembly_loaded(MonoAssemblyName *);
extern MonoImage *mono_assembly_get_image(MonoAssembly *);
extern const char *mono_image_get_guid(MonoImage *);
extern MonoClass *mono_class_get(MonoImage *, uint32_t);
extern MonoMethod *mono_get_method(MonoImage *, uint32_t, MonoClass *);
extern MonoObject *mono_object_new(MonoDomain *, MonoClass *);
extern MonoObject *mono_runtime_invoke(MonoMethod *, void *, void **, MonoObject **);
extern uint32_t mono_gchandle_new(MonoObject *, int);
extern MonoObject *mono_gchandle_get_target(uint32_t);
extern void mono_gchandle_free(uint32_t);

static int descriptor = -1;
static atomic_uint posted, observed;
static uint32_t callback_handle, context_handle;
static uintptr_t sender_thread;

static void record(const char *phase, int value);
static int stopped(int code) {
    record("STOPPED_BEFORE_POST", code);
    if (callback_handle) mono_gchandle_free(callback_handle);
    if (context_handle) mono_gchandle_free(context_handle);
    callback_handle = context_handle = 0;
    if (descriptor >= 0) sceKernelClose(descriptor);
    descriptor = -1;
    return code;
}

static void record(const char *phase, int value) {
    char line[160];
    int count = snprintf(line, sizeof(line), "%s %d\n", phase, value);
    if (descriptor >= 0 && count > 0 && count < (int)sizeof(line)) {
        sceKernelWrite(descriptor, line, (size_t)count);
        sceKernelFsync(descriptor);
    }
}

static int invoke(MonoMethod *method, MonoObject *target, void **args) {
    if (!method) return 0;
    MonoObject *exception = NULL;
    mono_runtime_invoke(method, target, args, &exception);
    if (exception) record("MANAGED_EXCEPTION", 1);
    return exception == NULL;
}

static void callback(void *state) {
    uintptr_t thread = (uintptr_t)scePthreadSelf();
    record("DIFFERENT_THREAD", thread != sender_thread);
    record("NULL_STATE", state == NULL);
    record("CALLBACK_COUNT", (int)atomic_fetch_add(&observed, 1) + 1);
    /* Not a proof of UI ownership or rendering, just one queued callback. */
}

int module_start(size_t argc, const void *argv) {
    (void)argc; (void)argv;
    struct arfoxia_process_info info;
    memset(&info, 0, sizeof(info));
    if (arfoxia_sdk(0, NULL) != 0x100 || arfoxia_sdk(4, &info) < 0 ||
        strncmp(info.name, "SceShellUI", sizeof(info.name)) != 0) return -1;
    OrbisKernelSwVersion firmware;
    memset(&firmware, 0, sizeof(firmware));
    firmware.Size = sizeof(firmware);
    if (sceKernelGetSystemSwVersion(&firmware) < 0 || firmware.Version != 0x12520001) return -2;
    descriptor = sceKernelOpen("/user/data/Arfoxia/dispatch-v1.txt", 0xa01, 0600);
    if (descriptor < 0) return -3;  /* EXCLUSIVE: never overwrite a prior run. */
    sender_thread = (uintptr_t)scePthreadSelf();
    record("ARFOXIA_DISPATCH_PROBE", 1);
    record("PHASE_ROOT_DOMAIN", 0);
    MonoDomain *domain = mono_get_root_domain();
    if (!domain || !mono_thread_attach(domain)) return stopped(-5);
    record("PHASE_FIND_LOADED_PUI", 0);
    MonoAssemblyName *name = mono_assembly_name_new("Sce.PlayStation.PUI");
    if (!name) return stopped(-6);
    MonoAssembly *assembly = mono_assembly_loaded(name);
    mono_assembly_name_free(name);
    MonoImage *pui = assembly ? mono_assembly_get_image(assembly) : NULL;
    MonoImage *corlib = mono_get_corlib();
    if (!pui || !corlib) return stopped(-7);
    const char *pui_guid = mono_image_get_guid(pui), *corlib_guid = mono_image_get_guid(corlib);
    if (!arfoxia_guid_equal(pui_guid, ARFOXIA_PUI_GUID) || !arfoxia_guid_equal(corlib_guid, ARFOXIA_CORLIB_GUID)) {
        record("PROFILE_MISMATCH", 1);
        return stopped(-8);
    }
    record("PHASE_CONTEXT_TYPE", 0);
    MonoClass *context_class = mono_class_get(pui, ARFOXIA_CONTEXT_TYPE);
    record("PHASE_CALLBACK_TYPE", 0);
    MonoClass *callback_class = mono_class_get(corlib, ARFOXIA_CALLBACK_TYPE);
    if (!context_class || !callback_class) return stopped(-9);
    record("PHASE_CONSTRUCTORS", 0);
    MonoMethod *context_ctor = mono_get_method(pui, ARFOXIA_CONTEXT_CTOR, context_class);
    MonoMethod *callback_ctor = mono_get_method(corlib, ARFOXIA_CALLBACK_CTOR, callback_class);
    MonoMethod *post = mono_get_method(pui, ARFOXIA_CONTEXT_POST, context_class);
    if (!context_ctor || !callback_ctor || !post) return stopped(-10);
    record("PHASE_NEW_CONTEXT", 0);
    MonoObject *context = mono_object_new(domain, context_class);
    if (!context) return stopped(-11);
    context_handle = mono_gchandle_new(context, 1);
    if (!context_handle || !invoke(context_ctor, context, NULL)) return stopped(-12);
    record("PHASE_NEW_CALLBACK", 0);
    MonoObject *delegate = mono_object_new(domain, callback_class);
    if (!delegate) return stopped(-13);
    callback_handle = mono_gchandle_new(delegate, 1);
    void *address = (void *)(uintptr_t)&callback;
    void *constructor_args[] = {NULL, &address};
    if (!callback_handle || !invoke(callback_ctor, delegate, constructor_args)) return stopped(-14);
    record("PHASE_POST", 0);
    void *args[] = {mono_gchandle_get_target(callback_handle), NULL};
    atomic_store(&posted, 1);
    if (!invoke(post, mono_gchandle_get_target(context_handle), args)) {
        record("POST_FAILED_KEEP_MODULE_LOADED", 1);
        return 0; /* Never unload code that may already have been queued. */
    }
    record("POST_RETURNED", 1);
    /* No waits or more callbacks on ShellUI's loader thread. The module and GC
     * handles stay alive: a timeout must not release pending executable code.
     */
    return 0;
}

int module_stop(size_t argc, const void *argv) {
    (void)argc; (void)argv;
    if (atomic_load(&posted)) return -1;  /* No premature unload of queued code. */
    if (callback_handle) mono_gchandle_free(callback_handle);
    if (context_handle) mono_gchandle_free(context_handle);
    if (descriptor >= 0) sceKernelClose(descriptor);
    return 0;
}
#endif
