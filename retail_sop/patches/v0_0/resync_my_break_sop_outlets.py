from retail_sop.patches.v0_0.seed_my_break_sop import execute as reexecute

# seed_my_break_sop already ran once on any site that's had it deployed
# before - patches only ever run once per site - so it never fires again
# for outlets that get marked Active *after* that first run. This is a
# fresh, separate patch entry whose only job is to re-invoke that same
# creation logic again. Safe to do on any site, any number of times:
# _create_template() inside it only ever creates a template that doesn't
# already exist by name, so nothing already on a site gets touched,
# duplicated, or overwritten - this only fills in whatever's still missing
# for outlets that weren't active the first time it ran.


def execute():
	reexecute()
