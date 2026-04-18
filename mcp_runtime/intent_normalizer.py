# mcp_runtime/intent_normalizer.py

import re
from typing import Dict


class IntentNormalizationError(Exception):
    pass


class IntentNormalizer:
    """
    Phase 4.x:
    Normalize free-text intent into canonical form.
    Supports partial (ambiguous) intents for clarification.
    """

    def normalize(self, intent: str) -> Dict:
        """
        Returns:
        {
            "action": "...",
            "object": "...",
            "scope": {...},
            "canonical": "..."
        }
        """

        if not intent or not intent.strip():
            raise IntentNormalizationError("Empty intent")

        text = intent.strip().lower()

        # ---- Normalize synonyms ----
        text = text.replace("list", "show")
        text = text.replace("display", "show")

        # =====================================================
        # FULL patterns
        # =====================================================

        # show switches in fabric <fabric>
        m = re.match(r"show\s+switches\s+in\s+fabric\s+(.+)", text)
        if m:
            fabric = m.group(1).strip()
            return {
                "action": "show",
                "object": "switches",
                "scope": {"fabric": fabric},
                "canonical": f"show switches in fabric {fabric}",
            }

        # show device <device>
        m = re.match(r"show\s+device\s+(.+)", text)
        if m:
            device = m.group(1).strip()
            return {
                "action": "show",
                "object": "device",
                "scope": {"device": device},
                "canonical": f"show device {device}",
            }

        # =====================================================
        # PARTIAL / AMBIGUOUS patterns (Phase 4.6)
        # =====================================================

        # show switches
        if text == "show switches":
            return {
                "action": "show",
                "object": "switches",
                "scope": {},           # ← missing fabric
                "canonical": "show switches",
            }

        # show device
        if text == "show device":
            return {
                "action": "show",
                "object": "device",
                "scope": {},           # ← missing device
                "canonical": "show device",
            }

        # =====================================================
        # Unknown intent
        # =====================================================
        raise IntentNormalizationError(
            f"Unrecognized intent pattern: '{intent}'"
        )
