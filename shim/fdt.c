/*
 * Just enough flattened-device-tree parsing to find what ABL put in
 * /chosen (initrd location). Big-endian, 4-byte aligned tokens.
 */
#include "fdt.h"

#define FDT_MAGIC	0xd00dfeed
#define FDT_BEGIN_NODE	1
#define FDT_END_NODE	2
#define FDT_PROP	3
#define FDT_NOP		4
#define FDT_END		9

static uint32_t be32(uintptr_t a)
{
	return __builtin_bswap32(*(volatile uint32_t *)a);
}

static int streq(const char *a, const char *b)
{
	while (*a && *a == *b)
		a++, b++;
	return *a == *b;
}

static uintptr_t align4(uintptr_t a)
{
	return (a + 3) & ~3UL;
}

static uintptr_t skip_str(uintptr_t p)
{
	/* byte loads are fine on Device memory as long as they are aligned to 1 */
	while (*(volatile char *)p)
		p++;
	return p + 1;
}

int fdt_chosen_u64(uintptr_t fdt, const char *prop, uint64_t *out)
{
	if (!fdt || be32(fdt) != FDT_MAGIC)
		return 0;
	uintptr_t p = fdt + be32(fdt + 8);		/* off_dt_struct */
	uintptr_t strings = fdt + be32(fdt + 12);	/* off_dt_strings */
	int depth = 0, in_chosen = 0;

	for (;;) {
		uint32_t tok = be32(p);
		p += 4;
		switch (tok) {
		case FDT_BEGIN_NODE: {
			const char *name = (const char *)p;
			depth++;
			in_chosen = depth == 2 && streq(name, "chosen");
			p = align4(skip_str(p));
			break;
		}
		case FDT_END_NODE:
			if (in_chosen)
				return 0;
			depth--;
			break;
		case FDT_PROP: {
			uint32_t len = be32(p), nameoff = be32(p + 4);
			uintptr_t val = p + 8;
			if (in_chosen && streq((const char *)(strings + nameoff), prop)) {
				if (len == 4)
					*out = be32(val);
				else if (len == 8)
					*out = (uint64_t)be32(val) << 32 | be32(val + 4);
				else
					return 0;
				return 1;
			}
			p = align4(val + len);
			break;
		}
		case FDT_NOP:
			break;
		default:	/* FDT_END or garbage */
			return 0;
		}
	}
}

/*
 * Highest address covered by the live /memory nodes, for the RAM-window guard
 * in loader.c.  ABL writes the real banks here (the base DTB's /memory is a
 * placeholder): 2G at 0x80000000 plus one bank at 0x1_00000000 whose size is
 * 0xfcc00000 on a 6 GB courbet and 0x17cc00000 on an 8 GB one.  SM7150 uses
 * #address-cells = #size-cells = 2, so every entry is four big-endian cells.
 */
int fdt_memory_top(uintptr_t fdt, uint64_t *top)
{
	if (!fdt || be32(fdt) != FDT_MAGIC)
		return 0;
	uintptr_t p = fdt + be32(fdt + 8);		/* off_dt_struct */
	uintptr_t strings = fdt + be32(fdt + 12);	/* off_dt_strings */
	int depth = 0, mem_depth = 0;
	uint64_t best = 0;

	for (;;) {
		uint32_t tok = be32(p);
		p += 4;
		switch (tok) {
		case FDT_BEGIN_NODE: {
			const char *name = (const char *)p;
			depth++;
			if (depth == 2 && name[0] == 'm' && name[1] == 'e' &&
			    name[2] == 'm' && name[3] == 'o' && name[4] == 'r' &&
			    name[5] == 'y' && (name[6] == '\0' || name[6] == '@'))
				mem_depth = depth;
			p = align4(skip_str(p));
			break;
		}
		case FDT_END_NODE:
			if (depth == mem_depth)
				mem_depth = 0;
			depth--;
			break;
		case FDT_PROP: {
			uint32_t len = be32(p), nameoff = be32(p + 4);
			uintptr_t val = p + 8;
			if (mem_depth && len >= 16 && (len & 15u) == 0 &&
			    streq((const char *)(strings + nameoff), "reg")) {
				for (uint32_t o = 0; o < len; o += 16) {
					uint64_t base = (uint64_t)be32(val + o) << 32 |
					    be32(val + o + 4);
					uint64_t size = (uint64_t)be32(val + o + 8) << 32 |
					    be32(val + o + 12);
					if (base + size > best)
						best = base + size;
				}
			}
			p = align4(val + len);
			break;
		}
		case FDT_NOP:
			break;
		default:	/* FDT_END or garbage */
			if (!best)
				return 0;
			*top = best;
			return 1;
		}
	}
}
