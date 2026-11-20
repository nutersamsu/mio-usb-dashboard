# Compila o MioDash.exe para o Mio C250 (Windows CE 5.0, ARMv4/ARM920T)
# Requer o toolchain CeGCC (arm-mingw32ce). Veja o README, secao "Compilar o cliente".
CC      := arm-mingw32ce-gcc
STRIP   := arm-mingw32ce-strip
CFLAGS  ?= -O2 -Wall -mcpu=arm920t
SAIDA   := MioDash.exe

all: $(SAIDA)

$(SAIDA): mio_dash.c
	$(CC) $(CFLAGS) -o $@ $<
	$(STRIP) $@
	@echo "OK: copie $(SAIDA) para sdcard/MioAutoRun/Apps/"

instalar: $(SAIDA)
	cp $(SAIDA) ../sdcard/MioAutoRun/Apps/

clean:
	rm -f $(SAIDA)

.PHONY: all instalar clean
