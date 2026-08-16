from .services import OrderService as Svc

import pkg.util as u


def main():
    svc = Svc()
    svc.save(1)
    return u.helper(2)


entry = u.helper
