from jarvis.memory import LocalMemory


def test_memory_stores_and_recalls_explicit_preference(tmp_path):
    memory = LocalMemory(str(tmp_path / "memory.sqlite3"), top_k=3)
    text = "Ricorda che preferisco risposte brevi per il progetto Jarvis"
    assert memory.remember_if_requested(text) is True
    assert text in memory.search("progetto Jarvis risposte")


def test_memory_blocks_obvious_secrets(tmp_path):
    memory = LocalMemory(str(tmp_path / "memory.sqlite3"), top_k=3)
    assert memory.remember_if_requested("Ricorda che la mia password è super-segreta") is False
    assert memory.recent() == []


def test_memory_can_be_deleted(tmp_path):
    memory = LocalMemory(str(tmp_path / "memory.sqlite3"), top_k=3)
    assert memory.remember("Ricorda che il progetto Jarvis usa LM Studio") is True
    item = memory.recent(1)[0]
    assert memory.forget(item.id) is True
    assert memory.recent() == []


def test_full_transcript_is_persistent_and_searchable(tmp_path):
    path = tmp_path / "memory.sqlite3"
    memory = LocalMemory(str(path), top_k=5)
    memory.record_turn(
        "Domani riprendiamo analisi matematica dagli integrali impropri",
        "Sì, signore. Ripartiremo dagli integrali impropri.",
        speaker="Andrea",
        metadata={"speaker_role": "owner"},
    )
    transcript = memory.recent_transcript(10)
    assert any("Andrea: Domani riprendiamo" in item.content for item in transcript)
    assert any("Jarvis: Sì, signore" in item.content for item in transcript)
    assert any("integrali impropri" in item for item in memory.search("integrali impropri"))
    memory.close()

    reopened = LocalMemory(str(path), top_k=5)
    assert any("integrali impropri" in item for item in reopened.search("integrali impropri"))


def test_transcript_redacts_obvious_secret_values(tmp_path):
    memory = LocalMemory(str(tmp_path / "memory.sqlite3"), top_k=3)
    memory.record_message("Andrea", "La password: super-segreta non va ripetuta")
    transcript = memory.recent_transcript(5)
    assert transcript
    assert "super-segreta" not in transcript[-1].content
    assert "[REDACTED]" in transcript[-1].content


def test_semantic_correction_supersedes_related_fact(tmp_path):
    memory = LocalMemory(str(tmp_path / "memory.sqlite3"), top_k=8)
    old = "Ricorda che il progetto FlixIT usa sempre il provider Alfa per lo streaming"
    correction = "Mi correggo, quello che ti ho detto sul progetto FlixIT era sbagliato: ora usa il provider Beta per lo streaming"
    assert memory.remember(old) is True
    memory.record_turn(correction, "Sì, signore.", speaker="Andrea")
    results = memory.search("progetto FlixIT provider streaming", top_k=8)
    assert correction in results
    assert old not in results
