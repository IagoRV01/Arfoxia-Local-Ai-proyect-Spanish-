/* HOST ONLY: validate a native delegate through a managed dispatch queue.
 * This deliberately does not use PS4 offsets, objects or Sony assemblies.
 * Host Mono success does NOT prove PS4/AOT compatibility.
 */
#include <mono/jit/jit.h>
#include <mono/metadata/assembly.h>
#include <mono/metadata/object.h>
#include <mono/metadata/class.h>
#include <mono/metadata/threads.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <time.h>
#include <string.h>

static atomic_uint observed;
static atomic_uint wrong_thread;
static pthread_t sender;

static void callback(void *state) {
    if (state != NULL || pthread_equal(sender, pthread_self()))
        atomic_store(&wrong_thread, 1);
    atomic_fetch_add(&observed, 1);
}

static int invoke(MonoMethod *method, MonoObject *target, void **args) {
    if (!method) return 0;
    MonoObject *exception = NULL;
    mono_runtime_invoke(method, target, args, &exception);
    if (exception) {
        MonoClass *klass = mono_object_get_class(exception);
        fprintf(stderr, "Managed exception: %s.%s\n", mono_class_get_namespace(klass),
            mono_class_get_name(klass));
        return 0;
    }
    return 1;
}

int main(int argc, char **argv) {
    if (argc != 2 && argc != 3) return 2;
    if (argc == 3) {
        if (strcmp(argv[2], "--full-aot") != 0) return 2;
        mono_jit_set_aot_mode(MONO_AOT_MODE_FULL);
    }
    sender = pthread_self();
    MonoDomain *domain = mono_jit_init_version("arfoxia-host-dispatch", "v4.0.30319");
    if (!domain) return 3;
    MonoAssembly *assembly = mono_domain_assembly_open(domain, argv[1]);
    if (!assembly) return 4;
    MonoClass *fixture = mono_class_from_name(mono_assembly_get_image(assembly), "", "ArfoxiaDispatchFixture");
    if (!fixture) return 5;
    MonoClass *delegate_class = mono_class_from_name(mono_get_corlib(), "System.Threading", "SendOrPostCallback");
    MonoMethod *constructor = mono_class_get_method_from_name(delegate_class, ".ctor", 2);
    MonoObject *delegate = mono_object_new(domain, delegate_class);
    if (!constructor || !delegate) return 6;
    uint32_t handle = mono_gchandle_new(delegate, 1);
    void *address = (void *)(uintptr_t)&callback;
    void *constructor_args[] = {NULL, &address};
    if (!invoke(constructor, delegate, constructor_args)) return 7;
    if (!invoke(mono_class_get_method_from_name(fixture, "Initialize", 0), NULL, NULL)) return 8;
    void *queue_args[] = {mono_gchandle_get_target(handle)};
    int posted = invoke(mono_class_get_method_from_name(fixture, "Enqueue", 1), NULL, queue_args);
    struct timespec delay = {0, 1000000};
    for (unsigned i=0; i < 3000 && !atomic_load(&observed); i++) nanosleep(&delay, NULL);
    int stopped = invoke(mono_class_get_method_from_name(fixture, "Stop", 0), NULL, NULL);
    unsigned seen = atomic_load(&observed), bad = atomic_load(&wrong_thread);
    mono_gchandle_free(handle);
    mono_jit_cleanup(domain);
    if (!posted || !stopped || seen != 1 || bad) return 9;
    puts("HOST dispatch passed: native delegate executed once on managed owner thread; NOT PS4 validation");
    return 0;
}
