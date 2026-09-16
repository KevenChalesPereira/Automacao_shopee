from __future__ import annotations

import ze_postavel_woodfrog_scene_voice_bubble_v4 as v4
import ze_postavel_woodfrog_voice_v5_scene4_final2 as final2

# Final lexical gate: the previous critical set did not include the main verb,
# so an ASR split like "desce congela" could slip through despite sounding wrong.
v4.CRITICAL_TOKENS[3].add("descongela")

if __name__ == "__main__":
    final2.final1.main()
