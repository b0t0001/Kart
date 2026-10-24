"""Cartesia Line entry point. Locally:  ANTHROPIC_API_KEY=… SUPABASE_URL=… SUPABASE_ANON_KEY=… PORT=8000 python main.py"""

import os

from line.voice_agent_app import VoiceAgentApp

from kart_agent.agent import KartAgent
from kart_agent.backend import SupabaseBackend
from kart_agent.brain import Brain
from kart_agent.llm import AnthropicLLM


async def get_agent(env, call_request):
    backend = SupabaseBackend(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
    agent = KartAgent(backend=backend, brain=Brain(llm=AnthropicLLM()), cart_id=os.getenv("CART_ID", "7"))
    return agent, agent.run_filter, agent.cancel_filter


app = VoiceAgentApp(get_agent=get_agent)

if __name__ == "__main__":
    app.run()
