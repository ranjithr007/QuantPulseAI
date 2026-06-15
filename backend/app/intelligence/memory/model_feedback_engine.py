class FeedbackEngine:

    def analyze_signal(self, trade):

        feedback = {}

        if trade.result == "WIN":

            feedback["action"] = "increase_weight"

        else:

            feedback["action"] = "reduce_weight"

        return feedback
