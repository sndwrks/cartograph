class Base:
    def save(self):
        return None


class Node(Base):
    def validate(self):
        return True


def render():
    return "models"
