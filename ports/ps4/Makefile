# Build in an isolated Linux environment; SDKs remain outside the repository.
OO_PS4_TOOLCHAIN ?= /opt/PS4Toolchain
PAYLOAD_SDK ?= /opt/ps4-payload-sdk
GOLDHEN_SDK ?= /opt/GoldHEN_Plugins_SDK
CC := clang-18
LD := ld.lld-18
TARGET_FLAGS := --target=x86_64-pc-freebsd12-elf -std=c11 -Wall -Wextra -Werror -fPIC -funwind-tables -isysroot $(OO_PS4_TOOLCHAIN) -isystem $(OO_PS4_TOOLCHAIN)/include

.PHONY: all test test-mono
all: build/arfoxia_probe.prx build/arfoxia_probe_loader.bin
test: build/test_goldhen_abi build/test_dispatch_contract
	./build/test_goldhen_abi
	./build/test_dispatch_contract
test-mono: build/dispatch_fixture.dll build/test_dispatch_mono
	./build/test_dispatch_mono build/dispatch_fixture.dll
build/dispatch_fixture.dll: tests/dispatch_fixture.cs | build
	mcs -target:library -out:$@ $<
build/test_dispatch_mono: tests/test_dispatch_mono.c | build
	gcc -std=gnu11 -Wall -Wextra -Werror $< -o $@ $$(pkg-config --cflags --libs mono-2) -pthread
build/test_goldhen_abi: tests/test_goldhen_abi.c native/goldhen_abi.h | build
	gcc -std=c11 -Wall -Wextra -Werror $< -o $@
build/test_dispatch_contract: tests/test_dispatch_contract.c native/dispatch_contract.h | build
	gcc -std=c11 -Wall -Wextra -Werror $< -o $@
build:
	mkdir -p build
build/probe.o: native/probe.c native/goldhen_abi.h | build
	$(CC) $(TARGET_FLAGS) -c $< -o $@
build/crtprx.o: $(GOLDHEN_SDK)/crt/crtprx.c | build
	$(CC) $(TARGET_FLAGS) -c $< -o $@
build/probe.elf: build/probe.o build/crtprx.o
	$(LD) -m elf_x86_64 -pie -e _init --script $(OO_PS4_TOOLCHAIN)/link.x --eh-frame-hdr -L$(OO_PS4_TOOLCHAIN)/lib $^ -lkernel -lSceLibcInternal -lmonosgen -o $@
build/arfoxia_probe.prx: build/probe.elf
	$(OO_PS4_TOOLCHAIN)/bin/linux/create-fself -in=$< -out=build/probe.oelf --lib=$@ --paid 0x3800000000000011
# The new diagnostic stays OFF by default and is NOT part of `all`.
# An explicitly enabled local build requires the generated PRIVATE profile.
build/dispatch_probe.o: native/dispatch_probe.c native/dispatch_contract.h native/goldhen_abi.h | build
	$(CC) $(TARGET_FLAGS) -c $< -o $@
build/dispatch_probe.elf: build/dispatch_probe.o build/crtprx.o
	$(LD) -m elf_x86_64 -pie -e _init --script $(OO_PS4_TOOLCHAIN)/link.x --eh-frame-hdr -L$(OO_PS4_TOOLCHAIN)/lib $^ -lkernel -lSceLibcInternal -lmonosgen -o $@
build/arfoxia_dispatch_v1.prx: build/dispatch_probe.elf
	$(OO_PS4_TOOLCHAIN)/bin/linux/create-fself -in=$< -out=build/dispatch_probe.oelf --lib=$@ --paid 0x3800000000000011
# Separate object/output: changing flags must never reuse a stale disabled file.
build/dispatch_candidate.o: native/dispatch_probe.c native/dispatch_contract.h native/goldhen_abi.h build/dispatch_profile.h | build
	$(CC) $(TARGET_FLAGS) -DARFOXIA_PS4_DISPATCH_PROBE_ENABLED=1 -Ibuild -c $< -o $@
build/dispatch_candidate.elf: build/dispatch_candidate.o build/crtprx.o
	$(LD) -m elf_x86_64 -pie -e _init --script $(OO_PS4_TOOLCHAIN)/link.x --eh-frame-hdr -L$(OO_PS4_TOOLCHAIN)/lib $^ -lkernel -lSceLibcInternal -lmonosgen -o $@
build/arfoxia_dispatch_candidate_v1.prx: build/dispatch_candidate.elf
	$(OO_PS4_TOOLCHAIN)/bin/linux/create-fself -in=$< -out=build/dispatch_candidate.oelf --lib=$@ --paid 0x3800000000000011
build/dispatch_owner.o: native/dispatch_probe.c native/dispatch_contract.h native/goldhen_abi.h build/dispatch_owner_profile.h | build
	$(CC) $(TARGET_FLAGS) -DARFOXIA_PS4_DISPATCH_PROBE_ENABLED=1 -DARFOXIA_PS4_QUERY_UI_OWNER=1 -Ibuild -c $< -o $@
build/dispatch_owner.elf: build/dispatch_owner.o build/crtprx.o
	$(LD) -m elf_x86_64 -pie -e _init --script $(OO_PS4_TOOLCHAIN)/link.x --eh-frame-hdr -L$(OO_PS4_TOOLCHAIN)/lib $^ -lkernel -lSceLibcInternal -lmonosgen -o $@
build/arfoxia_dispatch_candidate_v2.prx: build/dispatch_owner.elf
	$(OO_PS4_TOOLCHAIN)/bin/linux/create-fself -in=$< -out=build/dispatch_owner.oelf --lib=$@ --paid 0x3800000000000011
build/loader.o: native/loader.c native/goldhen_abi.h | build
	gcc -std=c11 -Os -ffreestanding -fno-builtin -fno-stack-protector -fPIE -masm=intel -m64 -mabi=sysv -I$(PAYLOAD_SDK)/libPS4/include -c $< -o $@
build/crt0.o: $(PAYLOAD_SDK)/libPS4/crt0.s | build
	gcc -c $< -o $@
build/loader.elf: build/crt0.o build/loader.o
	ld -pie --no-dynamic-linker -T $(PAYLOAD_SDK)/libPS4/linker.x -z max-page-size=0x4000 --gc-sections $^ -L$(PAYLOAD_SDK)/libPS4 -lPS4 -o $@
build/arfoxia_probe_loader.bin: build/loader.elf pack_payload.py
	python3 pack_payload.py $< $@
build/dispatch_loader.o: native/dispatch_loader.c | build
	gcc -std=c11 -Os -ffreestanding -fno-builtin -fno-stack-protector -fPIE -masm=intel -m64 -mabi=sysv -c $< -o $@
build/dispatch_loader_candidate.o: native/dispatch_loader.c native/goldhen_abi.h build/dispatch_profile.h | build
	gcc -std=c11 -Os -ffreestanding -fno-builtin -fno-stack-protector -fPIE -masm=intel -m64 -mabi=sysv -DARFOXIA_PS4_DISPATCH_LOADER_ENABLED=1 -Ibuild -I$(PAYLOAD_SDK)/libPS4/include -c $< -o $@
build/dispatch_loader.elf: build/crt0.o build/dispatch_loader.o
	ld -pie --no-dynamic-linker -T $(PAYLOAD_SDK)/libPS4/linker.x -z max-page-size=0x4000 --gc-sections $^ -L$(PAYLOAD_SDK)/libPS4 -lPS4 -o $@
build/dispatch_loader_candidate.elf: build/crt0.o build/dispatch_loader_candidate.o
	ld -pie --no-dynamic-linker -T $(PAYLOAD_SDK)/libPS4/linker.x -z max-page-size=0x4000 --gc-sections $^ -L$(PAYLOAD_SDK)/libPS4 -lPS4 -o $@
build/arfoxia_dispatch_loader_v1.bin: build/dispatch_loader.elf pack_payload.py
	python3 pack_payload.py $< $@
build/arfoxia_dispatch_loader_candidate_v1.bin: build/dispatch_loader_candidate.elf pack_payload.py
	python3 pack_payload.py $< $@
build/dispatch_loader_owner.o: native/dispatch_loader.c native/goldhen_abi.h build/dispatch_owner_profile.h | build
	gcc -std=c11 -Os -ffreestanding -fno-builtin -fno-stack-protector -fPIE -masm=intel -m64 -mabi=sysv -DARFOXIA_PS4_DISPATCH_LOADER_ENABLED=1 -DARFOXIA_PS4_QUERY_UI_OWNER=1 -Ibuild -I$(PAYLOAD_SDK)/libPS4/include -c $< -o $@
build/dispatch_loader_owner.elf: build/crt0.o build/dispatch_loader_owner.o
	ld -pie --no-dynamic-linker -T $(PAYLOAD_SDK)/libPS4/linker.x -z max-page-size=0x4000 --gc-sections $^ -L$(PAYLOAD_SDK)/libPS4 -lPS4 -o $@
build/arfoxia_dispatch_loader_candidate_v2.bin: build/dispatch_loader_owner.elf pack_payload.py
	python3 pack_payload.py $< $@
# Explicit temporary sprite experiment. Never part of normal `all`/autoload.
build/sprite_candidate.o: native/dispatch_probe.c native/sprite_preview.h native/dispatch_contract.h native/goldhen_abi.h build/dispatch_sprite_profile.h | build
	$(CC) $(TARGET_FLAGS) -DARFOXIA_PS4_DISPATCH_PROBE_ENABLED=1 -DARFOXIA_PS4_QUERY_UI_OWNER=1 -DARFOXIA_PS4_SPRITE_PREVIEW=1 -Ibuild -c $< -o $@
build/sprite_candidate.elf: build/sprite_candidate.o build/crtprx.o
	$(LD) -m elf_x86_64 -pie -e _init --script $(OO_PS4_TOOLCHAIN)/link.x --eh-frame-hdr -L$(OO_PS4_TOOLCHAIN)/lib $^ -lkernel -lSceLibcInternal -lmonosgen -o $@
build/arfoxia_sprite_candidate_v3.prx: build/sprite_candidate.elf
	$(OO_PS4_TOOLCHAIN)/bin/linux/create-fself -in=$< -out=build/sprite_candidate.oelf --lib=$@ --paid 0x3800000000000011
build/dispatch_loader_sprite.o: native/dispatch_loader.c native/goldhen_abi.h build/dispatch_sprite_profile.h | build
	gcc -std=c11 -Os -ffreestanding -fno-builtin -fno-stack-protector -fPIE -masm=intel -m64 -mabi=sysv -DARFOXIA_PS4_DISPATCH_LOADER_ENABLED=1 -DARFOXIA_PS4_QUERY_UI_OWNER=1 -DARFOXIA_PS4_SPRITE_PREVIEW=1 -Ibuild -I$(PAYLOAD_SDK)/libPS4/include -c $< -o $@
build/dispatch_loader_sprite.elf: build/crt0.o build/dispatch_loader_sprite.o
	ld -pie --no-dynamic-linker -T $(PAYLOAD_SDK)/libPS4/linker.x -z max-page-size=0x4000 --gc-sections $^ -L$(PAYLOAD_SDK)/libPS4 -lPS4 -o $@
build/arfoxia_sprite_loader_candidate_v3.bin: build/dispatch_loader_sprite.elf pack_payload.py
	python3 pack_payload.py $< $@
build/sprite_manager.o: native/dispatch_probe.c native/sprite_preview.h native/dispatch_contract.h native/goldhen_abi.h build/dispatch_sprite_manager_profile.h | build
	$(CC) $(TARGET_FLAGS) -DARFOXIA_PS4_DISPATCH_PROBE_ENABLED=1 -DARFOXIA_PS4_QUERY_UI_OWNER=1 -DARFOXIA_PS4_SPRITE_PREVIEW=1 -DARFOXIA_PS4_OWN_IMAGE_MANAGER=1 -Ibuild -c $< -o $@
build/sprite_manager.elf: build/sprite_manager.o build/crtprx.o
	$(LD) -m elf_x86_64 -pie -e _init --script $(OO_PS4_TOOLCHAIN)/link.x --eh-frame-hdr -L$(OO_PS4_TOOLCHAIN)/lib $^ -lkernel -lSceLibcInternal -lmonosgen -o $@
build/arfoxia_sprite_candidate_v4.prx: build/sprite_manager.elf
	$(OO_PS4_TOOLCHAIN)/bin/linux/create-fself -in=$< -out=build/sprite_manager.oelf --lib=$@ --paid 0x3800000000000011
build/dispatch_loader_manager.o: native/dispatch_loader.c native/goldhen_abi.h build/dispatch_sprite_manager_profile.h | build
	gcc -std=c11 -Os -ffreestanding -fno-builtin -fno-stack-protector -fPIE -masm=intel -m64 -mabi=sysv -DARFOXIA_PS4_DISPATCH_LOADER_ENABLED=1 -DARFOXIA_PS4_QUERY_UI_OWNER=1 -DARFOXIA_PS4_SPRITE_PREVIEW=1 -DARFOXIA_PS4_OWN_IMAGE_MANAGER=1 -Ibuild -I$(PAYLOAD_SDK)/libPS4/include -c $< -o $@
build/dispatch_loader_manager.elf: build/crt0.o build/dispatch_loader_manager.o
	ld -pie --no-dynamic-linker -T $(PAYLOAD_SDK)/libPS4/linker.x -z max-page-size=0x4000 --gc-sections $^ -L$(PAYLOAD_SDK)/libPS4 -lPS4 -o $@
build/arfoxia_sprite_loader_candidate_v4.bin: build/dispatch_loader_manager.elf pack_payload.py
	python3 pack_payload.py $< $@
# Explicitly release the owned image before its manager (v5, fresh paths/logs).
build/sprite_dispose.o: native/dispatch_probe.c native/sprite_preview.h native/dispatch_contract.h native/goldhen_abi.h build/dispatch_sprite_dispose_profile.h | build
	$(CC) $(TARGET_FLAGS) -DARFOXIA_PS4_DISPATCH_PROBE_ENABLED=1 -DARFOXIA_PS4_QUERY_UI_OWNER=1 -DARFOXIA_PS4_SPRITE_PREVIEW=1 -DARFOXIA_PS4_OWN_IMAGE_MANAGER=1 -DARFOXIA_PS4_DISPOSE_IMAGE_ASSET=1 -Ibuild -c $< -o $@
build/sprite_dispose.elf: build/sprite_dispose.o build/crtprx.o
	$(LD) -m elf_x86_64 -pie -e _init --script $(OO_PS4_TOOLCHAIN)/link.x --eh-frame-hdr -L$(OO_PS4_TOOLCHAIN)/lib $^ -lkernel -lSceLibcInternal -lmonosgen -o $@
build/arfoxia_sprite_candidate_v5.prx: build/sprite_dispose.elf
	$(OO_PS4_TOOLCHAIN)/bin/linux/create-fself -in=$< -out=build/sprite_dispose.oelf --lib=$@ --paid 0x3800000000000011
build/dispatch_loader_dispose.o: native/dispatch_loader.c native/goldhen_abi.h build/dispatch_sprite_dispose_profile.h | build
	gcc -std=c11 -Os -ffreestanding -fno-builtin -fno-stack-protector -fPIE -masm=intel -m64 -mabi=sysv -DARFOXIA_PS4_DISPATCH_LOADER_ENABLED=1 -DARFOXIA_PS4_QUERY_UI_OWNER=1 -DARFOXIA_PS4_SPRITE_PREVIEW=1 -DARFOXIA_PS4_OWN_IMAGE_MANAGER=1 -DARFOXIA_PS4_DISPOSE_IMAGE_ASSET=1 -Ibuild -I$(PAYLOAD_SDK)/libPS4/include -c $< -o $@
build/dispatch_loader_dispose.elf: build/crt0.o build/dispatch_loader_dispose.o
	ld -pie --no-dynamic-linker -T $(PAYLOAD_SDK)/libPS4/linker.x -z max-page-size=0x4000 --gc-sections $^ -L$(PAYLOAD_SDK)/libPS4 -lPS4 -o $@
build/arfoxia_sprite_loader_candidate_v5.bin: build/dispatch_loader_dispose.elf pack_payload.py
	python3 pack_payload.py $< $@
# Built-in UI2 sprite-sheet animation; still temporary and passive.
build/sprite_animation.o: native/dispatch_probe.c native/sprite_preview.h native/dispatch_contract.h native/goldhen_abi.h build/dispatch_sprite_animation_profile.h | build
	$(CC) $(TARGET_FLAGS) -DARFOXIA_PS4_DISPATCH_PROBE_ENABLED=1 -DARFOXIA_PS4_QUERY_UI_OWNER=1 -DARFOXIA_PS4_SPRITE_PREVIEW=1 -DARFOXIA_PS4_OWN_IMAGE_MANAGER=1 -DARFOXIA_PS4_DISPOSE_IMAGE_ASSET=1 -DARFOXIA_PS4_ANIMATED_PREVIEW=1 -Ibuild -c $< -o $@
build/sprite_animation.elf: build/sprite_animation.o build/crtprx.o
	$(LD) -m elf_x86_64 -pie -e _init --script $(OO_PS4_TOOLCHAIN)/link.x --eh-frame-hdr -L$(OO_PS4_TOOLCHAIN)/lib $^ -lkernel -lSceLibcInternal -lmonosgen -o $@
build/arfoxia_sprite_candidate_v6.prx: build/sprite_animation.elf
	$(OO_PS4_TOOLCHAIN)/bin/linux/create-fself -in=$< -out=build/sprite_animation.oelf --lib=$@ --paid 0x3800000000000011
build/dispatch_loader_animation.o: native/dispatch_loader.c native/goldhen_abi.h build/dispatch_sprite_animation_profile.h | build
	gcc -std=c11 -Os -ffreestanding -fno-builtin -fno-stack-protector -fPIE -masm=intel -m64 -mabi=sysv -DARFOXIA_PS4_DISPATCH_LOADER_ENABLED=1 -DARFOXIA_PS4_QUERY_UI_OWNER=1 -DARFOXIA_PS4_SPRITE_PREVIEW=1 -DARFOXIA_PS4_OWN_IMAGE_MANAGER=1 -DARFOXIA_PS4_DISPOSE_IMAGE_ASSET=1 -DARFOXIA_PS4_ANIMATED_PREVIEW=1 -Ibuild -I$(PAYLOAD_SDK)/libPS4/include -c $< -o $@
build/dispatch_loader_animation.elf: build/crt0.o build/dispatch_loader_animation.o
	ld -pie --no-dynamic-linker -T $(PAYLOAD_SDK)/libPS4/linker.x -z max-page-size=0x4000 --gc-sections $^ -L$(PAYLOAD_SDK)/libPS4 -lPS4 -o $@
build/arfoxia_sprite_loader_candidate_v6.bin: build/dispatch_loader_animation.elf pack_payload.py
	python3 pack_payload.py $< $@
# Bounded frame dispatch: static ImageBox, at most one outstanding UI callback.
SCHEDULED_FLAGS := -DARFOXIA_PS4_DISPATCH_PROBE_ENABLED=1 -DARFOXIA_PS4_QUERY_UI_OWNER=1 -DARFOXIA_PS4_SPRITE_PREVIEW=1 -DARFOXIA_PS4_OWN_IMAGE_MANAGER=1 -DARFOXIA_PS4_DISPOSE_IMAGE_ASSET=1 -DARFOXIA_PS4_SCHEDULED_FRAMES=1
build/sprite_scheduled.o: native/dispatch_probe.c native/sprite_preview.h native/dispatch_contract.h native/goldhen_abi.h build/dispatch_sprite_scheduled_profile.h | build
	$(CC) $(TARGET_FLAGS) $(SCHEDULED_FLAGS) -Ibuild -c $< -o $@
build/sprite_scheduled.elf: build/sprite_scheduled.o build/crtprx.o
	$(LD) -m elf_x86_64 -pie -e _init --script $(OO_PS4_TOOLCHAIN)/link.x --eh-frame-hdr -L$(OO_PS4_TOOLCHAIN)/lib $^ -lkernel -lSceLibcInternal -lmonosgen -o $@
build/arfoxia_sprite_candidate_v7.prx: build/sprite_scheduled.elf
	$(OO_PS4_TOOLCHAIN)/bin/linux/create-fself -in=$< -out=build/sprite_scheduled.oelf --lib=$@ --paid 0x3800000000000011
build/dispatch_loader_scheduled.o: native/dispatch_loader.c native/goldhen_abi.h build/dispatch_sprite_scheduled_profile.h | build
	gcc -std=c11 -Os -ffreestanding -fno-builtin -fno-stack-protector -fPIE -masm=intel -m64 -mabi=sysv $(SCHEDULED_FLAGS) -DARFOXIA_PS4_DISPATCH_LOADER_ENABLED=1 -Ibuild -I$(PAYLOAD_SDK)/libPS4/include -c $< -o $@
build/dispatch_loader_scheduled.elf: build/crt0.o build/dispatch_loader_scheduled.o
	ld -pie --no-dynamic-linker -T $(PAYLOAD_SDK)/libPS4/linker.x -z max-page-size=0x4000 --gc-sections $^ -L$(PAYLOAD_SDK)/libPS4 -lPS4 -o $@
build/arfoxia_sprite_loader_candidate_v7.bin: build/dispatch_loader_scheduled.elf pack_payload.py
	python3 pack_payload.py $< $@
# One-minute observable preview, with explicit aspect-preserving image scaling.
build/sprite_visible.o: native/dispatch_probe.c native/sprite_preview.h native/dispatch_contract.h native/goldhen_abi.h build/dispatch_sprite_visible_profile.h | build
	$(CC) $(TARGET_FLAGS) $(SCHEDULED_FLAGS) -DARFOXIA_PS4_VISIBLE_TEST=1 -Ibuild -c $< -o $@
build/sprite_visible.elf: build/sprite_visible.o build/crtprx.o
	$(LD) -m elf_x86_64 -pie -e _init --script $(OO_PS4_TOOLCHAIN)/link.x --eh-frame-hdr -L$(OO_PS4_TOOLCHAIN)/lib $^ -lkernel -lSceLibcInternal -lmonosgen -o $@
build/arfoxia_sprite_candidate_v8.prx: build/sprite_visible.elf
	$(OO_PS4_TOOLCHAIN)/bin/linux/create-fself -in=$< -out=build/sprite_visible.oelf --lib=$@ --paid 0x3800000000000011
build/dispatch_loader_visible.o: native/dispatch_loader.c native/goldhen_abi.h build/dispatch_sprite_visible_profile.h | build
	gcc -std=c11 -Os -ffreestanding -fno-builtin -fno-stack-protector -fPIE -masm=intel -m64 -mabi=sysv $(SCHEDULED_FLAGS) -DARFOXIA_PS4_VISIBLE_TEST=1 -DARFOXIA_PS4_DISPATCH_LOADER_ENABLED=1 -Ibuild -I$(PAYLOAD_SDK)/libPS4/include -c $< -o $@
build/dispatch_loader_visible.elf: build/crt0.o build/dispatch_loader_visible.o
	ld -pie --no-dynamic-linker -T $(PAYLOAD_SDK)/libPS4/linker.x -z max-page-size=0x4000 --gc-sections $^ -L$(PAYLOAD_SDK)/libPS4 -lPS4 -o $@
build/arfoxia_sprite_loader_candidate_v8.bin: build/dispatch_loader_visible.elf pack_payload.py
	python3 pack_payload.py $< $@
