/* Passive UI2 sprite experiments, best-effort removal after 15 seconds.
 * Included only by explicitly enabled, privately profiled experimental builds.
 */
typedef struct MonoString MonoString;
extern MonoString *mono_string_new(MonoDomain *, const char *);
extern MonoObject *mono_object_isinst(MonoObject *, MonoClass *);
extern void mono_thread_detach(MonoThread *);

static MonoDomain *preview_domain;
static MonoClass *preview_scene_class, *preview_asset_class, *preview_box_class;
static MonoClass *preview_APP, *preview_SCENE, *preview_ASSET, *preview_BOX, *preview_WIDGET, *preview_NODE;
static uint32_t preview_box_handle, preview_asset_handle, preview_cleanup_handle;
static int preview_box_ready, preview_attached;
static atomic_uint preview_state; /* 0 waiting, 1 attached, 2 skipped/failed */
static MonoMethod *preview_post;
static OrbisPthread preview_timer;
#if ARFOXIA_PS4_VISIBLE_TEST
static MonoMethod *preview_BOX_SCALE;
#endif
#if ARFOXIA_PS4_SCHEDULED_FRAMES
static uint32_t preview_frame_handles[4], preview_tick_handle;
static atomic_uint preview_tick_pending, preview_frames_halted;
static unsigned preview_frame_step;
#endif
#if ARFOXIA_PS4_ANIMATED_PREVIEW
static MonoMethod *preview_ANIM_WIDTH, *preview_ANIM_HEIGHT, *preview_ANIM_COUNT;
static MonoMethod *preview_ANIM_INTERVAL, *preview_ANIM_START, *preview_ANIM_STOP;
#endif
#if ARFOXIA_PS4_DISPOSE_IMAGE_ASSET
static MonoClass *preview_PROXY;
static MonoMethod *preview_ASSET_DISPOSE;
#endif
#if ARFOXIA_PS4_OWN_IMAGE_MANAGER
static MonoClass *preview_MANAGER;
static MonoMethod *preview_MANAGER_CTOR, *preview_MANAGER_LOAD, *preview_MANAGER_LIMIT, *preview_MANAGER_DISPOSE;
static uint32_t preview_manager_handle;
static int preview_manager_ready;
#endif

#define PREVIEW_METHODS(X) \
 X(APP_INSTANCE, APP) X(APP_ROOT, APP) X(SCENE_ROOT, SCENE) \
 X(ASSET_CTOR, ASSET) X(ASSET_WIDTH, ASSET) X(ASSET_HEIGHT, ASSET) \
 X(BOX_CTOR, BOX) X(BOX_IMAGE, BOX) X(WIDGET_TOUCH, WIDGET) \
 X(WIDGET_FOCUS, WIDGET) X(WIDGET_APPEND, WIDGET) X(WIDGET_REMOVE, WIDGET) \
 X(WIDGET_DISPOSE, WIDGET) X(NODE_X, NODE) X(NODE_Y, NODE) \
 X(NODE_WIDTH, NODE) X(NODE_HEIGHT, NODE) X(NODE_VISIBLE, NODE) \
 X(NODE_GET_WIDTH, NODE) X(NODE_GET_HEIGHT, NODE)
#define DECLARE_PREVIEW_METHOD(key, owner) static MonoMethod *preview_##key;
PREVIEW_METHODS(DECLARE_PREVIEW_METHOD)
#undef DECLARE_PREVIEW_METHOD

static int preview_prepare(MonoImage *pui, MonoDomain *domain, MonoMethod *post) {
    preview_domain = domain;
    preview_post = post;
#define RESOLVE_PREVIEW_CLASS(key) \
    preview_##key = mono_class_get(pui, ARFOXIA_SPRITE_##key##_TYPE); \
    if (!preview_##key) return 0;
    RESOLVE_PREVIEW_CLASS(APP)
    RESOLVE_PREVIEW_CLASS(SCENE)
    RESOLVE_PREVIEW_CLASS(ASSET)
    RESOLVE_PREVIEW_CLASS(BOX)
    RESOLVE_PREVIEW_CLASS(WIDGET)
    RESOLVE_PREVIEW_CLASS(NODE)
#if ARFOXIA_PS4_OWN_IMAGE_MANAGER
    RESOLVE_PREVIEW_CLASS(MANAGER)
#endif
#if ARFOXIA_PS4_DISPOSE_IMAGE_ASSET
    RESOLVE_PREVIEW_CLASS(PROXY)
#endif
#undef RESOLVE_PREVIEW_CLASS
    preview_scene_class = preview_SCENE;
    preview_asset_class = preview_ASSET;
    preview_box_class = preview_BOX;
#define RESOLVE_PREVIEW_METHOD(key, owner) \
    preview_##key = mono_get_method(pui, ARFOXIA_SPRITE_##key, \
        preview_##owner); \
    if (!preview_##key) return 0;
    PREVIEW_METHODS(RESOLVE_PREVIEW_METHOD)
#if ARFOXIA_PS4_OWN_IMAGE_MANAGER
    RESOLVE_PREVIEW_METHOD(MANAGER_CTOR, MANAGER)
    RESOLVE_PREVIEW_METHOD(MANAGER_LOAD, MANAGER)
    RESOLVE_PREVIEW_METHOD(MANAGER_LIMIT, MANAGER)
    RESOLVE_PREVIEW_METHOD(MANAGER_DISPOSE, MANAGER)
#endif
#if ARFOXIA_PS4_DISPOSE_IMAGE_ASSET
    RESOLVE_PREVIEW_METHOD(ASSET_DISPOSE, PROXY)
#endif
#if ARFOXIA_PS4_VISIBLE_TEST
    RESOLVE_PREVIEW_METHOD(BOX_SCALE, BOX)
#endif
#if ARFOXIA_PS4_ANIMATED_PREVIEW
    RESOLVE_PREVIEW_METHOD(ANIM_WIDTH, BOX)
    RESOLVE_PREVIEW_METHOD(ANIM_HEIGHT, BOX)
    RESOLVE_PREVIEW_METHOD(ANIM_COUNT, BOX)
    RESOLVE_PREVIEW_METHOD(ANIM_INTERVAL, BOX)
    RESOLVE_PREVIEW_METHOD(ANIM_START, BOX)
    RESOLVE_PREVIEW_METHOD(ANIM_STOP, BOX)
#endif
#undef RESOLVE_PREVIEW_METHOD
    return 1;
}

static MonoObject *preview_call(const char *phase, MonoMethod *method, MonoObject *target, void **args, int *ok) {
    record(phase, 0);
    MonoObject *exception = NULL;
    MonoObject *result = mono_runtime_invoke(method, target, args, &exception);
    *ok = exception == NULL;
    if (exception) record("PREVIEW_MANAGED_EXCEPTION", 1);
    return result;
}

static int preview_float(MonoMethod *method, MonoObject *target, float value) {
    void *args[] = {&value};
    return invoke(method, target, args);
}
static int preview_bool(MonoMethod *method, MonoObject *target, unsigned char value) {
    void *args[] = {&value};
    return invoke(method, target, args);
}
static int preview_bounds(MonoObject *parent, float *width, float *height) {
    int ok;
    MonoObject *w = preview_call("PHASE_PARENT_WIDTH", preview_NODE_GET_WIDTH, parent, NULL, &ok);
    void *value = ok && w ? mono_object_unbox(w) : NULL;
    if (!value) return 0;
    memcpy(width, value, sizeof(*width));
    MonoObject *h = preview_call("PHASE_PARENT_HEIGHT", preview_NODE_GET_HEIGHT, parent, NULL, &ok);
    value = ok && h ? mono_object_unbox(h) : NULL;
    if (!value) return 0;
    memcpy(height, value, sizeof(*height));
    /* Also rejects NaN/inf; no guessed viewport or off-screen coordinates. */
    return *width >= 320 && *width <= 8192 && *height >= 320 && *height <= 8192;
}

#if ARFOXIA_PS4_SCHEDULED_FRAMES
static int preview_load_frames(MonoObject *manager) {
    for (unsigned index=0; index<4; ++index) {
        char path[96];
        snprintf(path, sizeof(path), "/user/data/Arfoxia/walk-v7-%u.png", index);
        MonoString *uri = mono_string_new(preview_domain, path);
        uint32_t uri_handle = uri ? mono_gchandle_new((MonoObject *)uri, 1) : 0;
        if (!uri_handle) return 0;
        void *args[] = {mono_gchandle_get_target(uri_handle)};
        int ok;
        MonoObject *asset = preview_call("PHASE_LOAD_WALK_FRAME", preview_MANAGER_LOAD, manager, args, &ok);
        mono_gchandle_free(uri_handle);
        if (!ok || !asset || !mono_object_isinst(asset, preview_asset_class) ||
            !(preview_frame_handles[index] = mono_gchandle_new(asset, 1))) return 0;
        MonoObject *boxed = preview_call("PHASE_FRAME_WIDTH", preview_ASSET_WIDTH, asset, NULL, &ok);
        void *value = ok && boxed ? mono_object_unbox(boxed) : NULL;
        int width, height;
        if (!value) return 0;
        memcpy(&width, value, sizeof(width));
        boxed = preview_call("PHASE_FRAME_HEIGHT", preview_ASSET_HEIGHT, asset, NULL, &ok);
        value = ok && boxed ? mono_object_unbox(boxed) : NULL;
        if (!value) return 0;
        memcpy(&height, value, sizeof(height));
        if (width != 32 || height != 40) return 0;
    }
    record("WALK_FRAMES_LOADED", 4);
    return 1;
}

static void preview_tick(void *state) {
    (void)state;
    if (atomic_load(&preview_frames_halted) || atomic_load(&preview_state) != 1) goto done;
    MonoObject *exception = NULL;
    MonoObject *owner = mono_runtime_invoke(owner_query, NULL, NULL, &exception);
    void *value = owner && !exception ? mono_object_unbox(owner) : NULL;
    if (!value || !*(const unsigned char *)value) {
        record("FRAME_NOT_ON_UI_HALTED", 1);
        atomic_store(&preview_frames_halted, 1);
        goto done;
    }
    MonoObject *box = preview_box_handle ? mono_gchandle_get_target(preview_box_handle) : NULL;
    unsigned next = (preview_frame_step+1)%4;
    MonoObject *asset = mono_gchandle_get_target(preview_frame_handles[next]);
    if (!box || !asset) { atomic_store(&preview_frames_halted, 1); goto done; }
    void *args[] = {asset};
    if (!invoke(preview_BOX_IMAGE, box, args)) {
        atomic_store(&preview_frames_halted, 1);
        goto done;
    }
    ++preview_frame_step;
    if (preview_frame_step <= 8 || preview_frame_step%6 == 0) {
        record("FRAME_CHANGE_COUNT", (int)preview_frame_step);
        record("FRAME_IMAGE_INDEX", (int)next);
    }
done:
    atomic_store(&preview_tick_pending, 0);
}
#endif

static int preview_show(void) {
    int ok;
    MonoObject *app = preview_call("PHASE_APPLICATION", preview_APP_INSTANCE, NULL, NULL, &ok);
    if (!ok || !app) return 0;
    MonoObject *scene = preview_call("PHASE_ROOT_SCENE", preview_APP_ROOT, app, NULL, &ok);
    if (!ok || !scene || !mono_object_isinst(scene, preview_scene_class)) {
        record("ROOT_NOT_COMPATIBLE_UI2", 1);
        return 0;
    }
    MonoObject *parent = preview_call("PHASE_ROOT_WIDGET", preview_SCENE_ROOT, scene, NULL, &ok);
    float width, height;
    if (!ok || !parent || !preview_bounds(parent, &width, &height)) {
        record("INVALID_PARENT_BOUNDS", 1);
        return 0;
    }
#if ARFOXIA_PS4_OWN_IMAGE_MANAGER
    MonoObject *manager = mono_object_new(preview_domain, preview_MANAGER);
    if (!manager || !(preview_manager_handle = mono_gchandle_new(manager, 1))) return 0;
    MonoString *name = mono_string_new(preview_domain, "ArfoxiaTemporarySprite");
    uint32_t name_handle = name ? mono_gchandle_new((MonoObject *)name, 1) : 0;
    if (!name_handle) return 0;
    uint32_t limit = 262144; /* Own 256 KiB budget; never alter system managers. */
    void *manager_args[] = {mono_gchandle_get_target(name_handle), &limit};
    preview_call("PHASE_OWN_IMAGE_MANAGER", preview_MANAGER_CTOR, manager, manager_args, &ok);
    mono_gchandle_free(name_handle);
    if (!ok) return 0;
    preview_manager_ready = 1;
    MonoObject *boxed_limit = preview_call("PHASE_OWN_MANAGER_LIMIT", preview_MANAGER_LIMIT, manager, NULL, &ok);
    void *budget = ok && boxed_limit ? mono_object_unbox(boxed_limit) : NULL;
    uint32_t actual_limit;
    if (!budget) return 0;
    memcpy(&actual_limit, budget, sizeof(actual_limit));
    record("OWN_MANAGER_LIMIT", (int)actual_limit);
    if (actual_limit != limit) return 0;
#else
    MonoObject *asset = mono_object_new(preview_domain, preview_asset_class);
    if (!asset || !(preview_asset_handle = mono_gchandle_new(asset, 1))) return 0;
#endif
#if ARFOXIA_PS4_SCHEDULED_FRAMES
    if (!preview_load_frames(manager)) return 0;
    MonoObject *asset = mono_gchandle_get_target(preview_frame_handles[0]);
    if (!asset) return 0;
#else
#if ARFOXIA_PS4_ANIMATED_PREVIEW
    MonoString *uri = mono_string_new(preview_domain, "/user/data/Arfoxia/sprite-walk.png");
#else
    MonoString *uri = mono_string_new(preview_domain, "/user/data/Arfoxia/sprite-preview.png");
#endif
    uint32_t uri_handle = uri ? mono_gchandle_new((MonoObject *)uri, 1) : 0;
    if (!uri_handle) return 0;
    void *image_args[] = {mono_gchandle_get_target(uri_handle)};
#if ARFOXIA_PS4_OWN_IMAGE_MANAGER
    MonoObject *asset = preview_call("PHASE_IMAGE_ASSET", preview_MANAGER_LOAD, manager, image_args, &ok);
    mono_gchandle_free(uri_handle);
    if (!ok || !asset || !mono_object_isinst(asset, preview_asset_class) ||
        !(preview_asset_handle = mono_gchandle_new(asset, 1))) return 0;
#else
    preview_call("PHASE_IMAGE_ASSET", preview_ASSET_CTOR, asset, image_args, &ok);
    mono_gchandle_free(uri_handle);
    if (!ok) return 0;
#endif
#endif /* Static/sheet load; scheduled frame handles are separately owned. */
    MonoObject *image_width = preview_call("PHASE_IMAGE_WIDTH", preview_ASSET_WIDTH, asset, NULL, &ok);
    void *value = ok && image_width ? mono_object_unbox(image_width) : NULL;
    if (!value) return 0;
    int pixel_width;
    memcpy(&pixel_width, value, sizeof(pixel_width));
    MonoObject *image_height = preview_call("PHASE_IMAGE_HEIGHT", preview_ASSET_HEIGHT, asset, NULL, &ok);
    value = ok && image_height ? mono_object_unbox(image_height) : NULL;
    if (!value) return 0;
    int pixel_height;
    memcpy(&pixel_height, value, sizeof(pixel_height));
    record("IMAGE_WIDTH", pixel_width);
    record("IMAGE_HEIGHT", pixel_height);
#if ARFOXIA_PS4_SCHEDULED_FRAMES
    if (pixel_width != 32 || pixel_height != 40) return 0;
#elif ARFOXIA_PS4_ANIMATED_PREVIEW
    /* Existing PMD Walk sheet: 4 horizontal 32x40 frames, 8 direction rows. */
    if (pixel_width != 128 || pixel_height != 320) return 0;
#else
    if (pixel_width != 96 || pixel_height != 96) return 0;
#endif
    MonoObject *box = mono_object_new(preview_domain, preview_box_class);
    if (!box || !(preview_box_handle = mono_gchandle_new(box, 1))) return 0;
    preview_call("PHASE_IMAGE_BOX", preview_BOX_CTOR, box, NULL, &ok);
    if (!ok) return 0;
    preview_box_ready = 1;
#if ARFOXIA_PS4_VISIBLE_TEST
    /* Verified private enum: AspectInside=2. Scale rendering, not asset pixels. */
    int scale_type = 2;
    void *scale_args[] = {&scale_type};
    if (!invoke(preview_BOX_SCALE, box, scale_args)) return 0;
    record("ASPECT_INSIDE_SCALE", scale_type);
    record("VISIBLE_TEST_SECONDS", 60);
#endif
#if ARFOXIA_PS4_ANIMATED_PREVIEW
    int frame_width = 32, frame_height = 40, frame_count = 4;
    void *frame_width_args[] = {&frame_width}, *frame_height_args[] = {&frame_height}, *frame_count_args[] = {&frame_count};
    record("PHASE_CONFIGURE_ANIMATION", 0);
    if (!invoke(preview_ANIM_WIDTH, box, frame_width_args) ||
        !invoke(preview_ANIM_HEIGHT, box, frame_height_args) ||
        !invoke(preview_ANIM_COUNT, box, frame_count_args) ||
        !preview_float(preview_ANIM_INTERVAL, box, 1000.0f/6.0f)) return 0;
#endif
    record("PHASE_PASSIVE_GEOMETRY", 0);
    float display_height = (ARFOXIA_PS4_ANIMATED_PREVIEW || ARFOXIA_PS4_SCHEDULED_FRAMES) ? 240.0f : 192.0f;
    if (!preview_bool(preview_WIDGET_TOUCH, box, 0) || !preview_bool(preview_WIDGET_FOCUS, box, 0) ||
        !preview_float(preview_NODE_WIDTH, box, 192) || !preview_float(preview_NODE_HEIGHT, box, display_height) ||
        !preview_float(preview_NODE_X, box, width-240) || !preview_float(preview_NODE_Y, box, height-display_height-48) ||
        !preview_bool(preview_NODE_VISIBLE, box, 1)) return 0;
    void *assign[] = {asset};
    preview_call("PHASE_ASSIGN_IMAGE", preview_BOX_IMAGE, box, assign, &ok);
    if (!ok) return 0;
    void *append[] = {box};
    preview_call("PHASE_APPEND_SPRITE", preview_WIDGET_APPEND, parent, append, &ok);
    /* An exception may have occurred AFTER the UI mutation. Retain for cleanup. */
    preview_attached = 1;
    if (!ok) return 0;
#if ARFOXIA_PS4_ANIMATED_PREVIEW
    preview_call("PHASE_START_ANIMATION", preview_ANIM_START, box, NULL, &ok);
    if (!ok) return 0;
    record("ANIMATION_REQUESTED_NOT_VISUAL_PROOF", 1);
#endif
    record("PREVIEW_ATTACHED_NOT_VISUAL_PROOF", 1);
    return 1;
}

static void preview_cleanup(void *state) {
    (void)state;
#if ARFOXIA_PS4_SCHEDULED_FRAMES
    /* A pending/late frame callback must never access disposed UI objects. */
    atomic_store(&preview_frames_halted, 1);
#endif
    int ok;
    MonoObject *owner = preview_call("PHASE_CLEANUP_UI_OWNER", owner_query, NULL, NULL, &ok);
    void *value = ok && owner ? mono_object_unbox(owner) : NULL;
    if (!value || !*(const unsigned char *)value) {
        record("CLEANUP_NOT_ON_UI_RETAIN_ROOTS", 1);
        return;
    }
    MonoObject *box = preview_box_handle ? mono_gchandle_get_target(preview_box_handle) : NULL;
    if (box && preview_box_ready) {
#if ARFOXIA_PS4_ANIMATED_PREVIEW
        preview_call("PHASE_STOP_ANIMATION", preview_ANIM_STOP, box, NULL, &ok);
        if (!ok) return;
#endif
        if (preview_attached) {
            preview_call("PHASE_REMOVE_SPRITE", preview_WIDGET_REMOVE, box, NULL, &ok);
            if (!ok) return;
            preview_attached = 0;
        }
        preview_call("PHASE_DISPOSE_SPRITE", preview_WIDGET_DISPOSE, box, NULL, &ok);
        if (!ok) return;
    }
#if ARFOXIA_PS4_DISPOSE_IMAGE_ASSET
#if ARFOXIA_PS4_SCHEDULED_FRAMES
    for (unsigned index=0; index<4; ++index) {
        MonoObject *asset = preview_frame_handles[index] ? mono_gchandle_get_target(preview_frame_handles[index]) : NULL;
        if (asset) {
            preview_call("PHASE_DISPOSE_OWN_FRAME", preview_ASSET_DISPOSE, asset, NULL, &ok);
            if (!ok) return;
            mono_gchandle_free(preview_frame_handles[index]);
            preview_frame_handles[index] = 0;
        }
    }
#else
    MonoObject *asset = preview_asset_handle ? mono_gchandle_get_target(preview_asset_handle) : NULL;
    if (asset) {
        preview_call("PHASE_DISPOSE_OWN_IMAGE", preview_ASSET_DISPOSE, asset, NULL, &ok);
        if (!ok) return; /* Retain image/manager roots if explicit cleanup fails. */
    }
#endif
#endif
    if (preview_box_handle) mono_gchandle_free(preview_box_handle);
    if (preview_asset_handle) mono_gchandle_free(preview_asset_handle);
    preview_box_handle = preview_asset_handle = 0;
#if ARFOXIA_PS4_OWN_IMAGE_MANAGER
    MonoObject *manager = preview_manager_handle ? mono_gchandle_get_target(preview_manager_handle) : NULL;
    if (manager && preview_manager_ready) {
        preview_call("PHASE_DISPOSE_OWN_MANAGER", preview_MANAGER_DISPOSE, manager, NULL, &ok);
        if (!ok) return;
        preview_manager_ready = 0;
    }
    if (preview_manager_handle) mono_gchandle_free(preview_manager_handle);
    preview_manager_handle = 0;
#endif
    record("PREVIEW_CLEANED", 1);
    /* Callback/context roots and PRX remain alive; no forced unload. */
}

static void *preview_wait_then_remove(void *unused) {
    (void)unused;
    for (unsigned i=0; i<100 && !atomic_load(&preview_state); ++i) sceKernelUsleep(100000);
    unsigned state = atomic_load(&preview_state);
    if (!state) { record("PREVIEW_START_TIMEOUT_RETAIN_ROOTS", 1); return NULL; }
#if !ARFOXIA_PS4_SCHEDULED_FRAMES
    if (state == 1) sceKernelUsleep(15000000); /* Never sleep on the UI thread. */
#endif
    MonoThread *thread = mono_thread_attach(preview_domain);
    if (!thread) { record("CLEANUP_THREAD_ATTACH_FAILED", 1); return NULL; }
#if ARFOXIA_PS4_SCHEDULED_FRAMES
    if (state == 1) {
        unsigned slots = ARFOXIA_PS4_VISIBLE_TEST ? 360 : 90;
        for (unsigned tick=0; tick<slots; ++tick) {
            sceKernelUsleep(166667); /* Worker only; bounded 15/60 seconds. */
            if (atomic_load(&preview_frames_halted)) break;
            unsigned expected = 0;
            if (!atomic_compare_exchange_strong(&preview_tick_pending, &expected, 1)) continue;
            void *frame_args[] = {mono_gchandle_get_target(preview_tick_handle), NULL};
            if (!invoke(preview_post, mono_gchandle_get_target(context_handle), frame_args)) {
                record("FRAME_POST_FAILED_HALTED", 1);
                atomic_store(&preview_frames_halted, 1);
                break;
            }
        }
    }
#endif
    void *args[] = {mono_gchandle_get_target(preview_cleanup_handle), NULL};
    record("PHASE_QUEUE_CLEANUP", 0);
    if (invoke(preview_post, mono_gchandle_get_target(context_handle), args)) record("CLEANUP_POST_RETURNED", 1);
    mono_thread_detach(thread);
    return NULL;
}

static int preview_start_timer(MonoClass *callback_class, MonoMethod *callback_ctor) {
    MonoObject *cleanup = mono_object_new(preview_domain, callback_class);
    if (!cleanup || !(preview_cleanup_handle = mono_gchandle_new(cleanup, 1))) return 0;
    void *address = (void *)(uintptr_t)&preview_cleanup;
    void *args[] = {NULL, &address};
    if (!invoke(callback_ctor, cleanup, args)) {
        mono_gchandle_free(preview_cleanup_handle);
        preview_cleanup_handle = 0;
        return 0;
    }
#if ARFOXIA_PS4_SCHEDULED_FRAMES
    MonoObject *tick = mono_object_new(preview_domain, callback_class);
    if (!tick || !(preview_tick_handle = mono_gchandle_new(tick, 1))) goto fail_timer;
    address = (void *)(uintptr_t)&preview_tick;
    if (!invoke(callback_ctor, tick, args)) goto fail_timer;
#endif
    if (scePthreadCreate(&preview_timer, NULL, preview_wait_then_remove, NULL, "ArfoxiaPreview") != 0) goto fail_timer;
    scePthreadDetach(preview_timer);
    return 1;
fail_timer:
#if ARFOXIA_PS4_SCHEDULED_FRAMES
    if (preview_tick_handle) mono_gchandle_free(preview_tick_handle);
    preview_tick_handle = 0;
#endif
    mono_gchandle_free(preview_cleanup_handle);
    preview_cleanup_handle = 0;
    return 0;
}
