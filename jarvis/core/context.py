class ConversationContext:

    def __init__(self):
        self.messages = []


    def add(self, role, text):

        self.messages.append({
            "role": role,
            "text": text
        })


    def last(self):

        if self.messages:
            return self.messages[-1]

        return None