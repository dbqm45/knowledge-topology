from kt.topology.lineage import match_clusters


def test_lineage_continued_split_merged_new():
    prev = {"A": {"1", "2", "3", "4"}, "B": {"5", "6", "7"}, "C": {"8", "9", "10"}}
    new = [{"1", "2", "3", "4", "x"},  # continued A
           {"5", "6", "7", "8", "9", "10"},  # B and C merged
           {"20", "21", "22"}]  # brand new
    res = match_clusters(new, prev)
    assert res[0].key == "A" and res[0].relation == "continued"
    assert res[1].relation == "merged_from" and set(res[1].previous_keys) == {"B", "C"}
    assert res[2].relation == "new" and res[2].key.startswith("dom_")


def test_lineage_split():
    prev = {"A": {str(i) for i in range(10)}}
    res = match_clusters([{str(i) for i in range(6)}, {"6", "7", "8", "9"}], prev)
    assert res[0].key == "A" and res[0].relation == "continued"
    assert res[1].relation == "split_from" and res[1].previous_keys == ["A"]
