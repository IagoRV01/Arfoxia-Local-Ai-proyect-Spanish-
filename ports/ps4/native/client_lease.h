/* Included only by the owned resident client or host fake-kernel test. */
static int preview_refresh_lease(uint32_t *sequence, unsigned *remaining) {
    int fd=sceKernelOpen("/user/data/Arfoxia/control-v9.txt",0,0);
    if (fd >= 0) {
        char data[23];
        size_t count=sceKernelRead(fd,data,sizeof(data));
        sceKernelClose(fd);
        uint32_t received; unsigned mode;
        if (!arfoxia_parse_control(data,count,&received,&mode)) {
            record("CLIENT_INVALID_CONTROL_STOP",1);
            return 0;
        }
        if (received > *sequence) {
            unsigned previous=atomic_load(&preview_pet_mode);
            if (!*sequence || previous != mode) record("CLIENT_CONTROL_MODE",(int)mode);
            *sequence=received;
            *remaining=60; /* Ten seconds, independent of PS4 wall clock. */
            atomic_store(&preview_pet_mode,mode);
            if (mode == ARFOXIA_STOP) { record("CLIENT_MANUAL_STOP",1); return 0; }
        }
    }
    if (*remaining) --*remaining;
    if (!*remaining) { record("CLIENT_LEASE_EXPIRED_STOP",1); return 0; }
    return 1;
}
