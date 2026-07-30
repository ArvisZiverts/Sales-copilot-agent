from app.icp import company_name, load_icp, render_icp

REQUIRED_KEYS = {
    "company",
    "what_we_sell",
    "ideal_customer",
    "poor_fit",
    "scoring_rubric",
    "icebreaker_guidance",
}


def test_icp_file_loads_and_has_every_section():
    """A missing section silently degrades scoring quality — fail loudly instead."""
    icp = load_icp()
    assert REQUIRED_KEYS <= set(icp), f"missing: {REQUIRED_KEYS - set(icp)}"


def test_rubric_anchors_the_full_range():
    rubric = load_icp()["scoring_rubric"]
    assert {"9-10", "7-8", "5-6", "3-4", "1-2"} <= set(rubric)


def test_hard_disqualifiers_are_present():
    assert load_icp()["poor_fit"]["hard_disqualifiers"]


def test_renders_into_the_prompt():
    rendered = render_icp()
    assert "scoring_rubric" in rendered
    assert "hard_disqualifiers" in rendered
    assert company_name() in rendered
