class JarvisRouter:

    def classify(self, text):

        text = text.lower()

        if "gpu" in text or "computer" in text:
            return "system"

        if (
            "codice" in text
            or "github" in text
            or "progetto" in text
        ):
            return "developer"

        if (
            "apri" in text
            or "avvia" in text
        ):
            return "automation"

        return "general"