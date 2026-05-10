"""
Hand-curated authoritative seed chunks.

These cover the critical scenarios where automated scraping fails (ACOG
FAQs are JS-rendered, MedlinePlus topic pages are summary-only, etc.).
Every chunk is paraphrased from a cited authoritative source — patient
plain language, classified to the right action_type and tier_signal.

Sources cited inline in source_url. All content drawn from:
- ACOG Patient FAQ pages and Urgent Maternal Warning Signs (acog.org)
- CDC Hear Her campaign (cdc.gov/hearher)
- AWHONN Save Your Life campaign
- Postpartum Support International (postpartum.net)
- MedlinePlus (medlineplus.gov)

The text below is original paraphrase, not direct copy. Update as needed
when you find better wording for a given scenario.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from schema import LilyChunk  # noqa: E402


SEED_CHUNKS: list[LilyChunk] = [

    # ── ACOG Urgent Maternal Warning Signs (the 12 signs) ────────────────────
    LilyChunk(
        id="acog-warning-headache-vision",
        text=(
            "A severe headache that does not get better with rest or pain "
            "medicine, especially when it comes with changes in your vision "
            "like seeing spots, blurriness, or sensitivity to light, can be a "
            "sign of preeclampsia. This is a serious condition that needs "
            "emergency evaluation right away — do not wait."
        ),
        source="ACOG",
        source_url="https://www.acog.org/womens-health/infographics/urgent-maternal-warning-signs",
        topic="hypertension",
        subtopic="preeclampsia warning signs — severe headache and vision changes",
        gestational_relevance=["T2", "T3", "postpartum_early"],
        action_type="escalate",
        tier_signal="hand_off",
        severity="high",
        symptom_tags=["headache", "vision changes", "blood pressure"],
        plain_language=True,
        last_verified="2024",
    ),
    LilyChunk(
        id="acog-warning-bleeding-postpartum",
        text=(
            "Heavy bleeding after giving birth — soaking through more than one "
            "maxi pad in an hour, or passing blood clots larger than an egg — "
            "can be a sign of postpartum hemorrhage. This is a medical "
            "emergency and you need to be seen right away. Call 911 or go to "
            "the emergency room. Do not drive yourself."
        ),
        source="ACOG",
        source_url="https://www.acog.org/womens-health/infographics/urgent-maternal-warning-signs",
        topic="postpartum bleeding",
        subtopic="postpartum hemorrhage — heavy bleeding after birth",
        gestational_relevance=["postpartum_early"],
        action_type="escalate",
        tier_signal="hand_off",
        severity="high",
        symptom_tags=["bleeding", "postpartum"],
        plain_language=True,
        last_verified="2024",
    ),
    LilyChunk(
        id="acog-warning-chest-pain",
        text=(
            "Chest pain or trouble breathing during pregnancy or after birth "
            "can be a sign of a blood clot in the lungs or a heart problem. "
            "Both are emergencies. Call 911 or go to the emergency room "
            "immediately."
        ),
        source="ACOG",
        source_url="https://www.acog.org/womens-health/infographics/urgent-maternal-warning-signs",
        topic="cardiac",
        subtopic="chest pain or trouble breathing in pregnancy",
        gestational_relevance=["T1", "T2", "T3", "postpartum_early"],
        action_type="escalate",
        tier_signal="hand_off",
        severity="high",
        symptom_tags=["chest pain", "shortness of breath"],
        plain_language=True,
        last_verified="2024",
    ),
    LilyChunk(
        id="acog-warning-seizure",
        text=(
            "A seizure during pregnancy or in the first weeks after giving "
            "birth is an emergency. Call 911 immediately. This can be a sign "
            "of eclampsia, which is a severe complication of preeclampsia."
        ),
        source="ACOG",
        source_url="https://www.acog.org/womens-health/infographics/urgent-maternal-warning-signs",
        topic="hypertension",
        subtopic="seizure — eclampsia warning sign",
        gestational_relevance=["T2", "T3", "postpartum_early"],
        action_type="escalate",
        tier_signal="hand_off",
        severity="high",
        symptom_tags=["seizure"],
        plain_language=True,
        last_verified="2024",
    ),

    # ── PSI / postpartum depression — suicidal ideation ──────────────────────
    LilyChunk(
        id="psi-ppd-suicidal-thoughts",
        text=(
            "If you are having thoughts of harming yourself or your baby, or "
            "feeling like you don't want to be here anymore, you are not "
            "alone and this is not your fault. Postpartum depression and "
            "anxiety are real medical conditions that respond to treatment. "
            "You deserve help right now. We can connect you with a doctor "
            "today who specializes in postpartum mental health."
        ),
        source="PSI",
        source_url="https://www.postpartum.net/get-help/help-for-moms/",
        topic="postpartum mental health",
        subtopic="suicidal ideation — postpartum depression urgent support",
        gestational_relevance=["postpartum_early", "postpartum_late"],
        action_type="escalate",
        tier_signal="hand_up",
        severity="high",
        symptom_tags=["depression", "anxiety", "mood", "suicidal"],
        plain_language=True,
        last_verified="2024",
    ),
    LilyChunk(
        id="psi-ppd-coping",
        text=(
            "Feeling like you can't cope, crying often, or feeling "
            "disconnected from your baby for more than two weeks after birth "
            "is a sign of postpartum depression — not a personal failing. "
            "Many new mothers experience this. Talking to a clinician is the "
            "right first step. We can help connect you to one."
        ),
        source="PSI",
        source_url="https://www.postpartum.net/learn-more/",
        topic="postpartum mental health",
        subtopic="postpartum depression — symptoms and when to seek help",
        gestational_relevance=["postpartum_early", "postpartum_late"],
        action_type="monitor",
        tier_signal="hand_up",
        severity="medium",
        symptom_tags=["depression", "mood", "anxiety"],
        plain_language=True,
        last_verified="2024",
    ),

    # ── Reassurance: normal pregnancy/postpartum experiences ─────────────────
    LilyChunk(
        id="acog-normal-edema-feet",
        text=(
            "Mild swelling of the feet and ankles, especially at the end of "
            "the day or in warm weather, is very common in pregnancy. It "
            "happens because your body is holding more fluid and your growing "
            "uterus puts pressure on the veins in your legs. Putting your "
            "feet up, drinking water, and avoiding standing for long periods "
            "can help. This is not a cause for alarm by itself. However, "
            "swelling that comes on suddenly, is severe, or is paired with a "
            "headache or vision changes should be checked by a clinician right away."
        ),
        source="ACOG",
        source_url="https://www.acog.org/womens-health/faqs/preeclampsia-and-high-blood-pressure-during-pregnancy",
        topic="pregnancy normal symptoms",
        subtopic="mild edema and swelling — normal in pregnancy",
        gestational_relevance=["T2", "T3"],
        action_type="reassure",
        tier_signal="handle",
        severity="low",
        symptom_tags=["edema", "swelling"],
        plain_language=True,
        last_verified="2024",
    ),
    LilyChunk(
        id="medline-normal-fatigue",
        text=(
            "Feeling tired or fatigued during pregnancy is one of the most "
            "common and normal experiences, especially in the first and "
            "third trimesters. Your body is doing enormous work — growing a "
            "baby, increasing your blood volume, and adjusting your hormones. "
            "Rest when you can, eat regular small meals, drink water, and "
            "take short walks if you have the energy. If you are also "
            "feeling dizzy, very weak, or short of breath, mention that to "
            "your provider, but everyday tiredness on its own is normal."
        ),
        source="MedlinePlus",
        source_url="https://medlineplus.gov/pregnancy.html",
        topic="pregnancy normal symptoms",
        subtopic="fatigue and tiredness in pregnancy — normal",
        gestational_relevance=["T1", "T2", "T3", "postpartum_early"],
        action_type="reassure",
        tier_signal="handle",
        severity="low",
        symptom_tags=["fatigue"],
        plain_language=True,
        last_verified="2024",
    ),

    # ── Self-care: breastfeeding latch issues ────────────────────────────────
    LilyChunk(
        id="acog-breastfeeding-latch",
        text=(
            "Sore nipples and trouble getting your baby to latch are very "
            "common in the first weeks of breastfeeding and almost always "
            "improve with small adjustments. Make sure your baby's mouth "
            "covers as much of the areola as possible, not just the nipple. "
            "Bring your baby to your breast, not your breast to your baby. "
            "Try different positions like the football hold or laid-back "
            "nursing. Use a few drops of your own milk on the nipple after "
            "feeding to help it heal. If the pain is severe, you see "
            "bleeding cracks, or your baby isn't gaining weight, ask for a "
            "lactation consultant — your hospital usually has one for free."
        ),
        source="ACOG",
        source_url="https://www.acog.org/womens-health/faqs/breastfeeding-your-baby",
        topic="breastfeeding",
        subtopic="latch problems and sore nipples — self-care",
        gestational_relevance=["postpartum_early", "newborn"],
        action_type="self_care",
        tier_signal="handle",
        severity="low",
        symptom_tags=["latch", "nipple pain", "breastfeeding"],
        plain_language=True,
        last_verified="2024",
    ),

    # ── Monitor: postpartum bleeding (lochia) timeline ───────────────────────
    LilyChunk(
        id="acog-postpartum-bleeding-monitor",
        text=(
            "Bleeding after giving birth, called lochia, normally lasts about "
            "four to six weeks. It typically starts as bright red and heavy, "
            "becomes pinkish-brown over a couple of weeks, and ends as a "
            "yellowish-white discharge. Bleeding that stays heavy or bright "
            "red past the first week, comes with a fever, has a foul smell, "
            "or returns to heavy red bleeding after it had already lightened "
            "should be checked by a clinician — call your provider so they "
            "can review what is going on. Bleeding that soaks more than a "
            "pad in an hour, at any point, is an emergency."
        ),
        source="ACOG",
        source_url="https://www.acog.org/womens-health/faqs/postpartum-pain-management",
        topic="postpartum bleeding",
        subtopic="lochia — normal timeline and when to call a provider",
        gestational_relevance=["postpartum_early", "postpartum_late"],
        action_type="monitor",
        tier_signal="hand_up",
        severity="medium",
        symptom_tags=["bleeding", "lochia", "postpartum"],
        plain_language=True,
        last_verified="2024",
    ),

    # ── Navigate: WIC enrollment ─────────────────────────────────────────────
    LilyChunk(
        id="usda-wic-enrollment",
        text=(
            "WIC is a free federal program that provides healthy food, "
            "breastfeeding support, and nutrition counseling for pregnant "
            "and postpartum women, infants, and children up to age five. To "
            "apply, contact your state or local WIC office. You can find "
            "yours at signupwic.com or call 1-800-942-3678. You will need "
            "proof of identity, where you live, and your income. If you "
            "already get Medicaid, SNAP, or TANF, you usually qualify "
            "automatically. Most appointments can be done by phone or video "
            "now, especially for postpartum mothers."
        ),
        source="MedlinePlus",
        source_url="https://medlineplus.gov/wicwomeninfantsandchildren.html",
        topic="navigation",
        subtopic="WIC enrollment — how to apply",
        gestational_relevance=["T1", "T2", "T3", "postpartum_early", "postpartum_late"],
        action_type="navigate",
        tier_signal="none",
        severity="low",
        symptom_tags=[],
        plain_language=True,
        last_verified="2024",
    ),

    # ── A few more high-value warning signs to round out coverage ─────────────
    LilyChunk(
        id="acog-warning-leg-pain-clot",
        text=(
            "Pain, swelling, redness, or warmth in one leg, especially the "
            "calf, can be a sign of a blood clot. Pregnancy and the weeks "
            "right after birth raise your risk. Do not massage the leg. Call "
            "your provider or go to the emergency room right away."
        ),
        source="ACOG",
        source_url="https://www.acog.org/womens-health/infographics/urgent-maternal-warning-signs",
        topic="cardiac",
        subtopic="leg pain or swelling — possible blood clot",
        gestational_relevance=["T1", "T2", "T3", "postpartum_early"],
        action_type="escalate",
        tier_signal="hand_off",
        severity="high",
        symptom_tags=["leg pain", "swelling", "swollen leg", "calf pain"],
        plain_language=True,
        last_verified="2024",
    ),
    LilyChunk(
        id="acog-warning-fever-postpartum",
        text=(
            "A fever above 100.4 degrees Fahrenheit (38 degrees Celsius) "
            "after giving birth can be a sign of an infection. Call your "
            "provider the same day. If the fever comes with chills, "
            "abdominal pain, or foul-smelling discharge, go to the "
            "emergency room."
        ),
        source="ACOG",
        source_url="https://www.acog.org/womens-health/infographics/urgent-maternal-warning-signs",
        topic="postpartum infection",
        subtopic="postpartum fever — possible infection",
        gestational_relevance=["postpartum_early"],
        action_type="escalate",
        tier_signal="hand_off",
        severity="high",
        symptom_tags=["fever"],
        plain_language=True,
        last_verified="2024",
    ),
]
