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
static MonoMethod *owner_query;
static MonoMethod *preview_arguments;
static MonoDomain *fixture_domain;
static MonoMethod *enqueue;
static uint32_t callback_handle;
static atomic_uint worker_failed;

static void callback(void *state) {
    if (state != NULL || pthread_equal(sender, pthread_self()))
        atomic_store(&wrong_thread, 1);
    MonoObject *exception = NULL;
    MonoObject *boxed = mono_runtime_invoke(owner_query, NULL, NULL, &exception);
    const unsigned char *value = boxed && !exception ? mono_object_unbox(boxed) : NULL;
    if (!value || !*value) atomic_store(&wrong_thread, 1);
    float size = 192;
    uint32_t budget = 262144;
    unsigned char passive = 0;
    MonoString *uri = mono_string_new(fixture_domain, "owned-preview.png");
    uint32_t uri_handle = uri ? mono_gchandle_new((MonoObject *)uri, 1) : 0;
    if (!uri_handle) {
        atomic_store(&wrong_thread, 1);
    } else {
        void *args[] = {&size, &passive, mono_gchandle_get_target(uri_handle), mono_gchandle_get_target(uri_handle), &budget};
        exception = NULL;
        boxed = mono_runtime_invoke(preview_arguments, NULL, args, &exception);
        value = boxed && !exception ? mono_object_unbox(boxed) : NULL;
        if (!value || !*value) atomic_store(&wrong_thread, 1);
        mono_gchandle_free(uri_handle);
    }
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

static void *cleanup_worker(void *unused) {
    (void)unused;
    MonoThread *thread = mono_thread_attach(fixture_domain);
    if (!thread) { atomic_store(&worker_failed, 1); return NULL; }
    void *args[] = {mono_gchandle_get_target(callback_handle)};
    if (!invoke(enqueue, NULL, args)) atomic_store(&worker_failed, 1);
    mono_thread_detach(thread);
    return NULL;
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
    fixture_domain = domain;
    MonoAssembly *assembly = mono_domain_assembly_open(domain, argv[1]);
    if (!assembly) return 4;
    MonoClass *fixture = mono_class_from_name(mono_assembly_get_image(assembly), "", "ArfoxiaDispatchFixture");
    if (!fixture) return 5;
    owner_query = mono_class_get_method_from_name(fixture, "IsOwnerThread", 0);
    preview_arguments = mono_class_get_method_from_name(fixture, "CheckPreviewArguments", 5);
    if (!owner_query || !preview_arguments) return 5;
    MonoClass *delegate_class = mono_class_from_name(mono_get_corlib(), "System.Threading", "SendOrPostCallback");
    MonoMethod *constructor = mono_class_get_method_from_name(delegate_class, ".ctor", 2);
    MonoObject *delegate = mono_object_new(domain, delegate_class);
    if (!constructor || !delegate) return 6;
    uint32_t handle = mono_gchandle_new(delegate, 1);
    callback_handle = handle;
    void *address = (void *)(uintptr_t)&callback;
    void *constructor_args[] = {NULL, &address};
    if (!invoke(constructor, delegate, constructor_args)) return 7;
    if (!invoke(mono_class_get_method_from_name(fixture, "Initialize", 0), NULL, NULL)) return 8;
    void *queue_args[] = {mono_gchandle_get_target(handle)};
    enqueue = mono_class_get_method_from_name(fixture, "Enqueue", 1);
    int posted = invoke(enqueue, NULL, queue_args);
    struct timespec delay = {0, 1000000};
    for (unsigned i=0; i < 3000 && !atomic_load(&observed); i++) nanosleep(&delay, NULL);
    pthread_t worker;
    if (pthread_create(&worker, NULL, cleanup_worker, NULL) != 0) return 10;
    pthread_join(worker, NULL);
    for (unsigned i=0; i < 3000 && atomic_load(&observed) < 2; i++) nanosleep(&delay, NULL);
    int stopped = invoke(mono_class_get_method_from_name(fixture, "Stop", 0), NULL, NULL);
    unsigned seen = atomic_load(&observed), bad = atomic_load(&wrong_thread);
    mono_gchandle_free(handle);
    mono_jit_cleanup(domain);
    if (!posted || !stopped || seen != 2 || bad || atomic_load(&worker_failed)) return 9;
    puts("HOST dispatch passed: two callbacks, worker requeue and float/bool/string/reference/uint ABI on owner thread; NOT PS4 validation");
    return 0;
}
