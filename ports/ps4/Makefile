# Build in an isolated Linux environment; SDKs remain outside the repository.
OO_PS4_TOOLCHAIN ?= /opt/PS4Toolchain
PAYLOAD_SDK ?= /opt/ps4-payload-sdk
GOLDHEN_SDK ?= /opt/GoldHEN_Plugins_SDK
CC := clang-18
LD := ld.lld-18
TARGET_FLAGS := --target=x86_64-pc-freebsd12-elf -std=c11 -Wall -Wextra -Werror -fPIC -funwind-tables -isysroot $(OO_PS4_TOOLCHAIN) -isystem $(OO_PS4_TOOLCHAIN)/include

.PHONY: all
all: build/arfoxia_probe.prx build/arfoxia_probe_loader.bin
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
build/loader.o: native/loader.c native/goldhen_abi.h | build
	gcc -std=c11 -Os -ffreestanding -fno-builtin -fno-stack-protector -fPIE -masm=intel -m64 -mabi=sysv -I$(PAYLOAD_SDK)/libPS4/include -c $< -o $@
build/crt0.o: $(PAYLOAD_SDK)/libPS4/crt0.s | build
	gcc -c $< -o $@
build/loader.elf: build/crt0.o build/loader.o
	ld -T $(PAYLOAD_SDK)/libPS4/linker.x -z max-page-size=0x4000 --gc-sections $^ -L$(PAYLOAD_SDK)/libPS4 -lPS4 -o $@
build/arfoxia_probe_loader.bin: build/loader.elf
	objcopy -O binary $< $@
