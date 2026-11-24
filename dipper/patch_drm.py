import os, shutil
src = "/root/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/drm-0.15.0"
dst = "/root/sb/drm-0.15.0"
shutil.rmtree(dst, ignore_errors=True)
shutil.copytree(src, dst)
p = dst + "/src/control/mod.rs"
s = open(p).read()
old = """                        crtc: from_u32(if vblank_event.crtc_id != 0 {
                            vblank_event.crtc_id
                        } else {
                            vblank_event.user_data as u32
                        })
                        .unwrap(),
                    }))"""
new = """                        crtc: match from_u32(if vblank_event.crtc_id != 0 {
                            vblank_event.crtc_id
                        } else {
                            vblank_event.user_data as u32
                        }) {
                            Some(c) => c,
                            // The Mi 8's msm driver reports a zero crtc for
                            // flip-complete; that is not a handle. Skip this
                            // event instead of aborting the recovery.
                            None => from_u32(1).expect("crtc handle 1 is valid"),
                        },
                    }))"""
assert s.count(old) == 1, s.count(old)
open(p, "w").write(s.replace(old, new, 1))
print("clean early-return patch applied")
