
def assert_mutation_guard(context):
    assert context is not None, "Mutation attempted without authenticated context"
    return True
