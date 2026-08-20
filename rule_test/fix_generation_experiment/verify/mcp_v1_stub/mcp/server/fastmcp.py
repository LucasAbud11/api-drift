class Context:
    def __init__(self, *a, **k):
        pass

def get_context():
    return None

class FastMCP:
    def __init__(self, *a, **k):
        pass
    def tool(self, *a, **k):
        def deco(f):
            return f
        return deco
    def add_tool(self, f, *a, **k):
        return f
    def run(self, *a, **k):
        pass
