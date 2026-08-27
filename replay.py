import json
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
import os
from dotenv import load_dotenv

load_dotenv(override=True)

def replay_trace(trace):
    print(f"--- Original Output ---")
    print(trace["raw_output"])
    
    # Reconstruct the prompt
    sys_prompt = trace["system_prompt"]
    human_prompt = trace["human_prompt"]
    
    # Run the model again
    model_params = trace["model_params"]
    llm = ChatGoogleGenerativeAI(model=model_params["model"], temperature=model_params["temperature"])
    
    messages = [
        SystemMessage(content=sys_prompt),
        HumanMessage(content=human_prompt)
    ]
    
    response = llm.invoke(messages)
    
    print(f"\n--- Replayed Output ---")
    print(response.content)

if __name__ == '__main__':
    traces = json.load(open('sampled_traces.json'))
    replay_trace(traces[0]) # pick trace 1
