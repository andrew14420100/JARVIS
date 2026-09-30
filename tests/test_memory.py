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
