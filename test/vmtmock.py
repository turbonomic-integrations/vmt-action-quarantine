class Session:
    def __init__(self, *args, **kwargs):
        self.__responses = kwargs['responses']
        self.__callcount = {k:0 for k in self.__responses.keys()}

    def __getattr__(self, name):
        def foo(*args, **kwargs):
            curidx = self.__callcount[name]
            self.__callcount[name] = self.__callcount[name] + 1
            return self.__responses[name][curidx]
        return foo
