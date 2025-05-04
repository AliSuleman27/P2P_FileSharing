import os
import uuid
import json
import openai
import logging
import subprocess
import re
import time
from typing import TypedDict
import networkx as nx
import matplotlib.pyplot as plt
import re
import time
import logging
import psycopg2
from psycopg2 import  OperationalError
from langgraph.graph import StateGraph, END
from prompts import *




# ------------------------------------------------------------------------------
# Logging Configuration
# ------------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Secure API Key
# ------------------------------------------------------------------------------
openai.api_key = "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"

# ------------------------------------------------------------------------------
# Type Definitions
# ------------------------------------------------------------------------------
class AgentState(TypedDict):
    conceptual_design: str
    logical_design: str
    cypher_generated: str  # New field for generated Cypher output
    cypher_execution_output: str  # New field for cypher execution result
    bdd_scenarios: str
    bdd_evaluation_report: str
    postgres_schema: str
    sql_schema_evaluation_report: str
    triggers_sql: str
    test_cases_sql: str
    evaluation_report: str
    error: str
    bdd_input: str
    token_usage: dict
    workflow_id: str
    schema_execution_output: str
    trigger_execution_output: str
    test_execution_output: str
    sql_schema_temp: str
    bdd_finalized: bool
    stored_procedures_sql: str
    views_sql: str
    schema_json: str
    trigger_list_json: str
    procedures_doc_json: str
    views_doc_json: str
    views_execution_output: str
    procedures_execution_output: str
    full_metadata_generated: str

# ------------------------------------------------------------------------------
# Utility Functions (File Save)
# ------------------------------------------------------------------------------
def save_file(directory: str, filename: str, content: str) -> None:
    try:
        os.makedirs(directory, exist_ok=True)
        filepath = os.path.join(directory, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Saved file: {filepath}")
    except Exception as e:
        logger.error(f"Error saving file {filename} in directory {directory}: {str(e)}")
        raise
def save_json_file(directory: str, filename: str, data: str | dict) -> None:
    os.makedirs(directory, exist_ok=True)
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            # keep as raw string
            pass
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    logger.info(f"Saved JSON: {path}")

# ------------------------------------------------------------------------------
# OpenAI Interaction Functions
# ------------------------------------------------------------------------------
def call_chatgpt4(prompt: str) -> dict:
    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful AI software assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        content = response.choices[0].message.content
        tokens = response.usage.total_tokens if hasattr(response, "usage") else 0
        return {"output": content, "question": "", "tokens": tokens}
    except Exception as e:
        logger.error(f"Error in call_chatgpt4: {str(e)}")
        return {"output": "", "question": str(e), "tokens": 0}

def call_chatgpt4_sys(system_prompt,user_prompt,assistant_prompt="") -> dict:
    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": assistant_prompt}
            ],
            temperature=0.3
        )
        content = response.choices[0].message.content
        tokens = response.usage.total_tokens if hasattr(response, "usage") else 0
        return {"output": content, "question": "", "tokens": tokens}
    except Exception as e:
        logger.error(f"Error in call_chatgpt4: {str(e)}")
        return {"output": "", "question": str(e), "tokens": 0}



def get_best_of_llm(prompt: str, n: int = 3, eval_metric: str = "length") -> dict:
    candidates = []
    total_tokens = 0
    for _ in range(n):
        response = call_chatgpt4(prompt)
        output = response["output"]
        tokens = response["tokens"]
        total_tokens += tokens
        if output:
            candidates.append(output)
    if not candidates:
        return {"output": "", "tokens": total_tokens, "score": 0}
    voting_prompt = get_voting_prompt(candidates)
    voting_response = call_chatgpt4(voting_prompt)
    try:
        import json
        voting_result = json.loads(voting_response["output"])
        winner_index = voting_result["best_candidate_number"] - 1
        logger.info(f"Voting chose Candidate {voting_result['best_candidate_number']}: {voting_result['reason']}")
        best_output = candidates[winner_index]
    except Exception as e:
        logger.warning(f"Voting failed: {str(e)}. Falling back to the first candidate.")
        best_output = candidates[0]
    return {"output": best_output, "tokens": total_tokens, "score": 1.0}

def get_voting_prompt(candidates: list, context: str = "BDD scenarios") -> str:
    formatted_candidates = "\n\n".join(
        f"Candidate {i+1}:\n{candidate}\n" for i, candidate in enumerate(candidates)
    )
    return f"""
You are a critical evaluator.

You are given multiple {context}. Your job is to vote for the best candidate based on:
- Completeness
- Correctness
- Clarity
- Best practices

Here are the candidates:

{formatted_candidates}

Vote for the best candidate. Return only JSON:
{{
  "best_candidate_number": 1, 2, or 3,
  "reason": "Short reason for your choice"
}}

ONLY respond with the JSON. Do not explain further.
"""

# ------------------------------------------------------------------------------
# Agent Functions (without KG updates)
# ------------------------------------------------------------------------------

def conceptual_design_agent(state: AgentState) -> AgentState:
    bdd_input = state.get("bdd_input", "")
    prompt = get_conceptual_design_agent_prompt(bdd_input)
    response = call_chatgpt4(prompt)
    if response["question"]:
        state["error"] = response["question"]
        return state
    state.setdefault("token_usage", {})["conceptual_design"] = response["tokens"]
    logger.info(f"Conceptual Design (Tokens: {response['tokens']}): {response['output']}")
    state["conceptual_design"] = response["output"]
    return state

def logical_design_agent(state: AgentState) -> AgentState:
    conceptual_output = state["conceptual_design"]
    prompt = get_logical_design_agent_prompt(conceptual_output)
    response = call_chatgpt4(prompt)
    if response["question"]:
        state["error"] = response["question"]
        return state
    state["token_usage"]["logical_design"] = response["tokens"]
    logger.info(f"Logical Design (Tokens: {response['tokens']}): {response['output']}")
    state["logical_design"] = response["output"]
    return state

def relationship_cypher_agent(state: AgentState) -> AgentState:
    """
    This agent generates networkx code to build a directed graph representing a logical database schema.
    It prompts the LLM to output strictly valid Python code using networkx to:
      - Create nodes for each table and attribute.
      - Create edges representing 'HAS_ATTRIBUTE', 'PRIMARY_KEY', and 'FOREIGN_KEY_TO' relationships.
    
    Extra formatting (quotes or code block markers) is stripped off before saving the code.
    """
    logical_design_text = state.get("logical_design", "")
    
    prompt = f"""
You are an expert in knowledge graphs and database schema design. You are provided a logical schema in JSON format that describes database tables (entities), their attributes, primary keys, and foreign key relationships.

Your tasks are:

- Analyze the schema and extract:
  - All tables and their attributes.
  - Primary key attributes.
  - Foreign key relationships, including referenced tables and attributes.
  - Cardinality and key-based dependencies between tables.

- Generate valid Python code using the `networkx` library that:
  - Creates nodes for each table.
  - Creates nodes for each attribute.
  - Adds relationships (edges) from tables to attributes.
  - Represents primary keys with a labeled edge.
  - Represents foreign key associations as directed edges, including reference information as edge attributes.

Constraints:

- Use only the `networkx` library.
- Use a directed graph (`nx.DiGraph()`).
- Represent tables and attributes as nodes with appropriate metadata.
- Use edge types like 'HAS_ATTRIBUTE', 'PRIMARY_KEY', and 'FOREIGN_KEY_TO' as the `type` attribute in edges.
- Output strictly valid Python code using `networkx`. No explanations, comments, or extra text.
- dont writ e the name of language even like in first line u type python no you  are not allowed ot do that
----ALERT-----
No need to write anything else no commentary no names such as python or else just staright code


Reference Schema Example:
"output": {{
  "User": {{
    "Attribute": ["User ID", "Name", "Email", "Password"],
    "Primary key": ["User ID"]
  }},
  "Audit Log": {{
    "Attribute": ["Log ID", "Timestamp", "Action", "User ID"],
    "Primary key": ["Log ID"],
    "Foreign key": {{
      "User ID": {{"User": "User ID"}}
    }}
  }}
}}

Reference NetworkX Output:

import networkx as nx

G = nx.DiGraph()

G.add_node("User", type="Table")
G.add_node("Audit Log", type="Table")

G.add_node("User ID", type="Attribute")
G.add_node("Name", type="Attribute")
G.add_node("Email", type="Attribute")
G.add_node("Password", type="Attribute")
G.add_edge("User", "User ID", type="HAS_ATTRIBUTE")
G.add_edge("User", "Name", type="HAS_ATTRIBUTE")
G.add_edge("User", "Email", type="HAS_ATTRIBUTE")
G.add_edge("User", "Password", type="HAS_ATTRIBUTE")

G.add_node("Log ID", type="Attribute")
G.add_node("Timestamp", type="Attribute")
G.add_node("Action", type="Attribute")
G.add_node("User ID", type="Attribute")
G.add_edge("Audit Log", "Log ID", type="HAS_ATTRIBUTE")
G.add_edge("Audit Log", "Timestamp", type="HAS_ATTRIBUTE")
G.add_edge("Audit Log", "Action", type="HAS_ATTRIBUTE")
G.add_edge("Audit Log", "User ID", type="HAS_ATTRIBUTE")

G.add_edge("User", "User ID", type="PRIMARY_KEY")
G.add_edge("Audit Log", "Log ID", type="PRIMARY_KEY")
G.add_edge("User ID", "User", type="FOREIGN_KEY_TO", references="User ID")


Input Logical Schema:
{logical_design_text}
"""
    # Get the generated code by calling the LLM with the prompt.
    response = call_chatgpt4(prompt)
    
    # If the LLM response contains clarifying questions, handle accordingly.
    if response.get("question"):
        state["error"] = response["question"]
        return state

    generated_code = response.get("output", "")
    
    # Remove any wrapping backticks or extra quotes from the generated code.
    generated_code = generated_code.strip().strip("`").strip("'").strip('"')
    if generated_code.startswith("```") and generated_code.endswith("```"):
        generated_code = generated_code[3:-3].strip()
    if generated_code.startswith("'''") and generated_code.endswith("'''"):
        generated_code = generated_code[3:-3].strip()
    if generated_code.startswith('"""') and generated_code.endswith('"""'):
        generated_code = generated_code[3:-3].strip()
    
    state.setdefault("token_usage", {})["relationship_cypher"] = response.get("tokens", 0)
    state["cypher_generated"] = generated_code

    workflow_id = state.get("workflow_id", "unknown")
    # Save the generated code to file for traceability. (File extension can be .py)
    save_file("ttl_nodes", f"relationship_{workflow_id}.py", generated_code)

    logger.info(f"Generated and cleaned networkx Python script:\n{generated_code}")
    return state

def execute_cypher_queries(state: AgentState) -> AgentState:
    """
    Executes the generated networkx Python code locally,
    saves the graph structure as a .graphml file,
    and saves a diagram as a .png image.
    """
    generated_code = state.get("cypher_generated", "")
    if not generated_code:
        state["error"] = "No generated networkx code found in state."
        return state

    # Create a dedicated namespace for execution
    local_vars = {}
    try:
        exec(generated_code, globals(), local_vars)
    except Exception as e:
        state["error"] = f"Error executing networkx code: {e}"
        return state

    if "G" not in local_vars:
        state["error"] = "Graph object 'G' not found after executing the code."
        return state

    # Retrieve graph
    G = local_vars["G"]
    nodes_count = len(G.nodes)
    edges_count = len(G.edges)
    summary = f"Graph created successfully with {nodes_count} nodes and {edges_count} edges."
    logger.info(summary)

    state["graph_summary"] = summary
    state["cypher_execution_output"] = "NetworkX graph created successfully"
    state["graph"] = G

    # Save GraphML file
    workflow_id = state.get("workflow_id", "unknown")
    graphml_path = f"ttl_nodes/{workflow_id}.graphml"
    nx.write_graphml(G, graphml_path)
    logger.info(f"Saved graph structure as GraphML at: {graphml_path}")

    # Save Graph PNG Image
    try:
        pos = nx.spring_layout(G, seed=42)  # Nice layout, consistent across runs
        plt.figure(figsize=(12, 8))  # Width x Height in inches
        nx.draw(G, pos, with_labels=True, arrows=True, node_size=1500, font_size=10)
        png_path = f"ttl_nodes/{workflow_id}.png"
        plt.savefig(png_path)
        plt.close()
        logger.info(f"Saved graph visualization as PNG at: {png_path}")
    except Exception as e:
        logger.warning(f"Could not generate graph PNG visualization: {str(e)}")

    return state


def bdd_generator_agent1(state: AgentState) -> AgentState:
    logical_output = state["logical_design"]
    prompt = get_bdd_generator_prompt(logical_output)
    response = get_best_of_llm(prompt, n=2, eval_metric="length")
    if not response["output"]:
        state["error"] = "BDD Generation 1 failed."
        return state
    state["token_usage"]["bdd_generator1"] = response["tokens"]
    logger.info(f"BDD Generator 1 (Tokens: {response['tokens']}): {response['output']}")
    state["bdd_scenarios"] = response["output"]
    return state

def evaluate_bdd_agent(state: AgentState) -> AgentState:
    bdd_output = state["bdd_scenarios"]
    prompt = get_BDD_eval_agent_prompt(bdd_output)
    response = call_chatgpt4(prompt)
    if response["question"]:
        state["error"] = response["question"]
        return state
    logger.info(f"BDD Evaluation Result: {response['output']}")
    state["bdd_evaluation_report"] = response["output"]
    return state

def bdd_generator_agent2(state: AgentState) -> AgentState:
    logical_output = state["logical_design"]
    previous_bdd = state.get("bdd_scenarios", "")
    evaluation_feedback = state.get("bdd_evaluation_report", "")
    system_prompt, user_prompt, assistant_directive = get_bdd_generator_node2_prompts(logical_output, previous_bdd, evaluation_feedback)
    response = call_chatgpt4_sys(system_prompt, user_prompt, assistant_directive)
    if not response["output"]:
        state["error"] = "BDD Generation 2 failed."
        return state
    state["token_usage"]["bdd_generator2"] = response["tokens"]
    workflow_id = state.get("workflow_id")
    if workflow_id:
        save_file("bdd_nodes", f"{workflow_id}.feature", response["output"])
    logger.info(f"BDD Generator 2 (Tokens: {response['tokens']}): {response['output']}")
    state["bdd_scenarios"] = response["output"]
    state["bdd_finalized"] = True
    return state

def postgres_schema_agent1(state: AgentState) -> AgentState:
    bdd_output = state["bdd_scenarios"]
    logical_output = state["logical_design"]
    user_prompt, system_prompt = get_postgresql_schema_generator_prompts(bdd_output,logical_output)
    response = call_chatgpt4_sys(user_prompt, system_prompt)
    if not response["output"]:
        state["error"] = "PostgreSQL Schema Generation 1 failed."
        return state
    state["token_usage"]["postgres_schema_agent1"] = response["tokens"]
    sql_temp = response["output"]
    if sql_temp.strip().startswith("sql"):
        sql_temp = sql_temp.strip().removeprefix("sql").removesuffix("").strip()
    logger.info(f"SQL Schema Generator 1 (Tokens: {response['tokens']}): {sql_temp}")
    state["sql_schema_temp"] = sql_temp
    return state

def evaluate_sql_schema_agent(state: AgentState) -> AgentState:
    sql_schema_temp = state.get("sql_schema_temp", "")
    prompt = get_SQL_schema_eval_agent_prompt(sql_schema_temp)
    response = call_chatgpt4(prompt)
    if response["question"]:
        state["error"] = response["question"]
        return state
    logger.info(f"SQL Schema Evaluation Result (Tokens: {response['tokens']}): {response['output']}")
    state["sql_schema_evaluation_report"] = response["output"]
    return state

def postgres_schema_agent2(state: AgentState) -> AgentState:
    bdd_output = state["bdd_scenarios"]
    evaluation_feedback = state.get("sql_schema_evaluation_report", "")
    sql_schema_temp = state.get("sql_schema_temp", "")
    logical_output = state["logical_design"]

    user_prompt, system_prompt, assistant_prompt = get_postgresql_schema_node2_prompts(logical_output, sql_schema_temp, evaluation_feedback)
    response = call_chatgpt4_sys(user_prompt, system_prompt, assistant_prompt)
    if not response["output"]:
        state["error"] = "PostgreSQL Schema Generation 2 failed."
        return state
    state["token_usage"]["postgres_schema_agent2"] = response["tokens"]
    workflow_id = state.get("workflow_id")
    raw_sql = response["output"]
    if raw_sql.strip().startswith("```sql"):
        raw_sql = raw_sql.strip().removeprefix("```sql").removesuffix("```").strip()
    if workflow_id:
        save_file("sql_nodes", f"{workflow_id}.sql", raw_sql)
    logger.info(f"SQL Schema Generator 2 (Tokens: {response['tokens']}): {raw_sql}")
    state["postgres_schema"] = raw_sql
    return state

def trigger_generation_agent(state: AgentState) -> AgentState:
    schema_sql = state.get("postgres_schema", "")
    user_prompt, system_prompt = get_trigger_generator_prompts(schema_sql)
    response = call_chatgpt4_sys( user_prompt, system_prompt)
    if not response["output"]:
        state["error"] = "Trigger generation failed."
        return state
    state["token_usage"]["trigger_generator"] = response["tokens"]
    workflow_id = state.get("workflow_id")
    trigger_sql = response["output"]
    if trigger_sql.strip().startswith("```sql"):
        trigger_sql = trigger_sql.strip().removeprefix("```sql").removesuffix("```").strip()
    elif trigger_sql.strip().startswith("```"):
        trigger_sql = trigger_sql.strip().removeprefix("```").removesuffix("```").strip()
    if workflow_id:
        save_file("trigger_nodes", f"{workflow_id}.sql", trigger_sql)
    logger.info(f"Trigger Definitions (Tokens: {response['tokens']}): {trigger_sql}")
    state["triggers_sql"] = trigger_sql
    return state

# — New JSON‑and‑SQL Documentation Nodes —

def stored_procedures_agent(state: AgentState) -> AgentState:
    # 1. Generate the CRUD stored procedure SQL from the schema + triggers
    ss = state.get("postgres_schema", "")
    ww = state.get("triggers_sql", "")
    zz = state.get("bdd_finalized","")
    user_prompt, system_prompt = get_crud_procedures_prompt(ss,ww,zz)
    response = call_chatgpt4_sys(user_prompt, system_prompt)

    # 2. Clean the raw output from the LLM
    raw_output = response.get("output", "")
    sql_text = raw_output.strip()
    if sql_text.startswith("```sql"):
        sql_text = sql_text.removeprefix("```sql").removesuffix("```").strip()

    # 3. Store tokens used and clean output in state
    state.setdefault("token_usage", {})["stored_procedures"] = response.get("tokens", 0)
    state["stored_procedures_sql"] = sql_text

    # 4. Save the cleaned SQL to a file
    save_file("sql_nodes", f"{state['workflow_id']}_procs.sql", sql_text)
    return state


def view_generation_agent(state: AgentState) -> AgentState:
    prompt = get_view_generation_prompt(state["postgres_schema"])
    r = call_chatgpt4(prompt)

    # 1. Pull out raw output and strip whitespace
    raw_output = r.get("output", "")
    sql_text = raw_output.strip()

    # 2. Remove triple-backtick fences if present
    if sql_text.startswith("```sql"):
        sql_text = sql_text.removeprefix("```sql").removesuffix("```").strip()

    # 3. Update token usage and state
    state.setdefault("token_usage", {})["view_generation"] = r.get("tokens", 0)
    state["views_sql"] = sql_text

    # 4. Save to disk
    save_file("sql_nodes", f"{state['workflow_id']}_views.sql", sql_text)
    return state


def schema_json_agent(state: AgentState) -> AgentState:
    prompt = get_schema_json_prompt(state["postgres_schema"])
    r = call_chatgpt4(prompt)

    # JSON may also come wrapped in fences—strip any backticks
    raw_output = r.get("output", "")
    json_text = raw_output.strip()
    if json_text.startswith("```"):
        json_text = json_text.strip("```").strip()

    # Update and save
    state.setdefault("token_usage", {})["schema_json"] = r.get("tokens", 0)
    state["schema_json"] = json_text
    save_json_file("json_nodes", f"{state['workflow_id']}_schema.json", json_text)
    return state


def trigger_list_agent(state: AgentState) -> AgentState:
    prompt = get_trigger_list_prompt(state["triggers_sql"])
    r = call_chatgpt4(prompt)

    # Clean JSON output
    raw_output = r.get("output", "")
    json_text = raw_output.strip()
    if json_text.startswith("```"):
        json_text = json_text.strip("```").strip()

    # Update and save
    state.setdefault("token_usage", {})["trigger_list"] = r.get("tokens", 0)
    state["trigger_list_json"] = json_text
    save_json_file("json_nodes", f"{state['workflow_id']}_triggers.json", json_text)
    return state


def procedures_doc_agent(state: AgentState) -> AgentState:
    prompt = get_procedures_doc_prompt(state["stored_procedures_sql"])
    r = call_chatgpt4(prompt)

    # Clean JSON output
    raw_output = r.get("output", "")
    json_text = raw_output.strip()
    if json_text.startswith("```"):
        json_text = json_text.strip("```").strip()

    # Update and save
    state.setdefault("token_usage", {})["proc_docs"] = r.get("tokens", 0)
    state["procedures_doc_json"] = json_text
    save_json_file("json_nodes", f"{state['workflow_id']}_proc_docs.json", json_text)
    return state


def views_doc_agent(state: AgentState) -> AgentState:
    prompt = get_views_doc_prompt(state["views_sql"])
    r = call_chatgpt4(prompt)

    # Clean JSON output
    raw_output = r.get("output", "")
    json_text = raw_output.strip()
    if json_text.startswith("```"):
        json_text = json_text.strip("```").strip()

    # Update and save
    state.setdefault("token_usage", {})["view_docs"] = r.get("tokens", 0)
    state["views_doc_json"] = json_text
    save_json_file("json_nodes", f"{state['workflow_id']}_view_docs.json", json_text)
    return state


def final_metadata_agent(state: AgentState) -> AgentState:
    try:
        combined = {
            "schema": json.loads(state["schema_json"]),
            "triggers": json.loads(state["trigger_list_json"]),
            "procedures": json.loads(state["procedures_doc_json"]),
            "views": json.loads(state["views_doc_json"]),
        }
        save_json_file("json_nodes", f"{state['workflow_id']}_full_metadata.json", combined)

        # Mark as done so we don't loop here
        state["full_metadata_generated"] = combined

    except Exception as e:
        state["error"] = f"Final metadata merge failed: {e}"
    return state

#work onn it
def sql_test_case_agent(state: AgentState) -> AgentState:
    bdd_output = state.get("bdd_scenarios", "")
    schema_sql = state.get("postgres_schema", "")
    triggers_sql = state.get("triggers_sql", "")
    stored_procs = state.get("stored_procedures_sql","")
    prompt = get_sql_test_generator_prompt(bdd_output, schema_sql, triggers_sql,stored_procs)
    response = call_chatgpt4(prompt)
    if not response["output"]:
        state["error"] = "SQL test case generation failed."
        return state
    state["token_usage"]["test_case_generator"] = response["tokens"]
    workflow_id = state.get("workflow_id")
    test_sql = response["output"]
    if test_sql.strip().startswith("```sql"):
        test_sql = test_sql.strip().removeprefix("```sql").removesuffix("```").strip()
    if workflow_id:
        save_file("test_nodes", f"{workflow_id}.sql", test_sql)
    logger.info(f"SQL Test Cases (Tokens: {response['tokens']}): {test_sql}")
    state["test_cases_sql"] = test_sql
    return state

def evaluation_agent(state: AgentState) -> AgentState:
    prompt = get_evaluation_prompt() + f"""
Evaluate the following outputs:

SQL Schema:
{state['postgres_schema']}

Triggers:
{state['triggers_sql']}

Test Cases:
{state['test_cases_sql']}
"""
    response = call_chatgpt4(prompt)
    if response["question"]:
        state["error"] = response["question"]
        return state
    logger.info(f"Evaluation Report (Tokens: {response['tokens']}): {response['output']}")
    if '"evaluation_result": "Approve"' not in response["output"]:
        state["error"] = "Evaluation rejected the generated outputs."
        return state
    state["evaluation_report"] = response["output"]
    return state

# ------------------------------------------------------------------------------
# Local Database Execution Functions (using subprocess/psql)
# ------------------------------------------------------------------------------
def open_yugabyte_connection(
    host: str = "localhost",
    port: int = 5433,
    dbname: str = "yugabyte",
    user: str = "yugabyte",
    password: str = "yugabyte",
    connect_timeout: int = 10
):
    """Open a psycopg2 connection to the YugabyteDB Docker instance."""
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            connect_timeout=connect_timeout
        )
        conn.autocommit = True
        return conn
    except OperationalError as e:
        logger.error(f"❌ Could not connect to YugabyteDB: {e}")
        raise

def execute_sql_file_whole(state: dict) -> dict:
    workflow_id = state.get("workflow_id")
    if not workflow_id:
        state["error"] = "Missing workflow_id"
        return state

    sql_file = f"sql_nodes/{workflow_id}.sql"
    logger.info(f"\n🚀 Executing full SQL file without splitting: {sql_file}")

    try:
        with open(sql_file, "r", encoding="utf-8") as f:
            full_sql = f.read()

        conn = open_yugabyte_connection()
        cur = conn.cursor()

        t0 = time.time()
        cur.execute(full_sql)
        t1 = time.time()

        duration = t1 - t0
        log = f"✅ Executed entire SQL file successfully in {duration:.2f} seconds."
        logger.info(log)
        state["schema_execution_output"] = log

    except Exception as e:
        logger.exception("❌ Full SQL file execution failed.")
        state["error"] = str(e)

    finally:
        try:
            cur.close()
            conn.close()
        except:
            pass

    return state

def execute_trigger_file(state: dict) -> dict:
    workflow_id = state.get("workflow_id")
    if not workflow_id:
        state["error"] = "Missing workflow_id."
        return state

    trigger_file = f"trigger_nodes/{workflow_id}.sql"
    logger.info(f"🚀 Executing Trigger file via psycopg2: {trigger_file}")

    try:
        sql_text = open(trigger_file, "r", encoding="utf-8").read()
        conn = open_yugabyte_connection()
        cur = conn.cursor()

        t0 = time.time()
        cur.execute(sql_text)
        t1 = time.time()

        msg = f"✅ Triggers applied in {t1 - t0:.2f}s"
        logger.info(msg)
        state["trigger_execution_output"] = msg

    except Exception as e:
        logger.exception("❌ Trigger execution failed")
        state["error"] = str(e)

    finally:
        try:
            cur.close()
            conn.close()
        except:
            pass

    return state

def execute_procedures_file(state: AgentState) -> AgentState:
    workflow_id = state.get("workflow_id")
    if not workflow_id:
        state["error"] = "Missing workflow_id."
        return state

    proc_file = f"sql_nodes/{workflow_id}_procs.sql"
    logger.info(f"🚀 Executing Stored Procedures: {proc_file}")

    try:
        sql_text = open(proc_file, "r", encoding="utf-8").read()
        conn = open_yugabyte_connection()
        cur = conn.cursor()

        t0 = time.time()
        cur.execute(sql_text)
        t1 = time.time()

        msg = f"✅ Stored procedures created in {t1 - t0:.2f}s"
        logger.info(msg)
        state["procedures_execution_output"] = msg

    except Exception as e:
        logger.exception("❌ Stored procedure execution failed")
        state["error"] = str(e)

    finally:
        try:
            cur.close()
            conn.close()
        except:
            pass

    return state

def execute_views_file(state: AgentState) -> AgentState:
    workflow_id = state.get("workflow_id")
    if not workflow_id:
        state["error"] = "Missing workflow_id."
        return state

    views_file = f"sql_nodes/{workflow_id}_views.sql"
    logger.info(f"🚀 Executing Views SQL: {views_file}")

    try:
        sql_text = open(views_file, "r", encoding="utf-8").read()
        conn = open_yugabyte_connection()
        cur = conn.cursor()

        t0 = time.time()
        cur.execute(sql_text)
        t1 = time.time()

        msg = f"✅ Views created in {t1 - t0:.2f}s"
        logger.info(msg)
        state["views_execution_output"] = msg

    except Exception as e:
        logger.exception("❌ View execution failed")
        state["error"] = str(e)

    finally:
        try:
            cur.close()
            conn.close()
        except:
            pass

    return state

def execute_test_cases(state: dict) -> dict:
    workflow_id = state.get("workflow_id")
    if not workflow_id:
        state["error"] = "Missing workflow_id."
        return state

    test_file = f"test_nodes/{workflow_id}.sql"
    logger.info(f"🚀 Executing Test Cases via psycopg2: {test_file}")

    try:
        sql_text = open(test_file, "r", encoding="utf-8").read()
        conn = open_yugabyte_connection()
        cur = conn.cursor()

        t0 = time.time()
        cur.execute(sql_text)
        results = cur.fetchall() if cur.description else []
        t1 = time.time()

        msg = f"✅ Tests ran in {t1 - t0:.2f}s; {len(results)} rows returned"
        logger.info(msg)
        state["test_execution_output"] = {
            "message": msg,
            "rows": results
        }

    except Exception as e:
        logger.exception("❌ Test execution failed")
        state["error"] = str(e)

    finally:
        try:
            cur.close()
            conn.close()
        except:
            pass

    return state


def route_to_next(state: AgentState):
    logger.info(f"Current state: {list(state.keys())}")

    if "error" in state and state["error"]:
        logger.error(f"Error found: {state['error']}")
        return END

    # Design → Cypher → BDD → SQL schema → triggers
    if "conceptual_design" not in state:
        return "conceptual_design_agent"
    if "logical_design" not in state:
        return "logical_design_agent"
    if "cypher_generated" not in state:
        return "relationship_cypher_agent"
    if "cypher_execution_output" not in state:
        return "execute_cypher_queries"
    if "bdd_scenarios" not in state:
        return "bdd_generator_agent1"
    if "bdd_evaluation_report" not in state:
        return "evaluate_bdd_agent"
    if not state.get("bdd_finalized", False):
        return "bdd_generator_agent2"
    if "sql_schema_temp" not in state:
        return "postgres_schema_agent1"
    if "sql_schema_evaluation_report" not in state:
        return "evaluate_sql_schema_agent"
    if "postgres_schema" not in state:
        return "postgres_schema_agent2"
    if "triggers_sql" not in state:
        return "trigger_generation_agent"

    # → Stored procs, views, JSON docs, metadata
    if "stored_procedures_sql" not in state:
        return "stored_procedures_agent"
    if "views_sql" not in state:
        return "view_generation_agent"
    if "schema_json" not in state:
        return "schema_json_agent"
    if "trigger_list_json" not in state:
        return "trigger_list_agent"
    if "procedures_doc_json" not in state:
        return "procedures_doc_agent"
    if "views_doc_json" not in state:
        return "views_doc_agent"
    if "full_metadata_generated" not in state:
        return "final_metadata_agent"

    # → SQL test‑cases
    if "test_cases_sql" not in state:
        return "sql_test_case_agent"
    if "evaluation_report" not in state:
        return "evaluation_agent"

    # → Apply schema & triggers & procs & views & tests
    if "schema_execution_output" not in state:
        return "execute_schema_file"
    if "trigger_execution_output" not in state:
        return "execute_trigger_file"
    if "procedures_execution_output" not in state:
        return "execute_procedures_file"
    if "views_execution_output" not in state:
        return "execute_views_file"
    if "test_execution_output" not in state:
        return "execute_test_cases"

    logger.info("No further steps, returning END.")
    return END


# ------------------------------------------------------------------------------
# Workflow Graph
# ------------------------------------------------------------------------------
workflow = StateGraph(AgentState)

# Core agents
workflow.add_node("conceptual_design_agent", conceptual_design_agent)
workflow.add_node("logical_design_agent", logical_design_agent)
workflow.add_node("relationship_cypher_agent", relationship_cypher_agent)
workflow.add_node("execute_cypher_queries", execute_cypher_queries)
workflow.add_node("bdd_generator_agent1", bdd_generator_agent1)
workflow.add_node("evaluate_bdd_agent", evaluate_bdd_agent)
workflow.add_node("bdd_generator_agent2", bdd_generator_agent2)
workflow.add_node("postgres_schema_agent1", postgres_schema_agent1)
workflow.add_node("evaluate_sql_schema_agent", evaluate_sql_schema_agent)
workflow.add_node("postgres_schema_agent2", postgres_schema_agent2)
workflow.add_node("trigger_generation_agent", trigger_generation_agent)

# New metadata‑generation agents
workflow.add_node("stored_procedures_agent", stored_procedures_agent)
workflow.add_node("view_generation_agent", view_generation_agent)
workflow.add_node("schema_json_agent", schema_json_agent)
workflow.add_node("trigger_list_agent", trigger_list_agent)
workflow.add_node("procedures_doc_agent", procedures_doc_agent)
workflow.add_node("views_doc_agent", views_doc_agent)
workflow.add_node("final_metadata_agent", final_metadata_agent)

# SQL test‑case agent
workflow.add_node("sql_test_case_agent", sql_test_case_agent)
workflow.add_node("evaluation_agent", evaluation_agent)

# Execution agents
workflow.add_node("execute_schema_file", execute_sql_file_whole)
workflow.add_node("execute_trigger_file", execute_trigger_file)
workflow.add_node("execute_procedures_file", execute_procedures_file)
workflow.add_node("execute_views_file", execute_views_file)
workflow.add_node("execute_test_cases", execute_test_cases)

# ------------------------------------------------------------------------------
# Conditional edges, in the natural order of execution:
# ------------------------------------------------------------------------------
workflow.add_conditional_edges("conceptual_design_agent", route_to_next, {
    "logical_design_agent": "logical_design_agent", END: END
})
workflow.add_conditional_edges("logical_design_agent", route_to_next, {
    "relationship_cypher_agent": "relationship_cypher_agent", END: END
})
workflow.add_conditional_edges("relationship_cypher_agent", route_to_next, {
    "execute_cypher_queries": "execute_cypher_queries", END: END
})
workflow.add_conditional_edges("execute_cypher_queries", route_to_next, {
    "bdd_generator_agent1": "bdd_generator_agent1", END: END
})
workflow.add_conditional_edges("bdd_generator_agent1", route_to_next, {
    "evaluate_bdd_agent": "evaluate_bdd_agent", END: END
})
workflow.add_conditional_edges("evaluate_bdd_agent", route_to_next, {
    "bdd_generator_agent2": "bdd_generator_agent2", END: END
})
workflow.add_conditional_edges("bdd_generator_agent2", route_to_next, {
    "postgres_schema_agent1": "postgres_schema_agent1", END: END
})
workflow.add_conditional_edges("postgres_schema_agent1", route_to_next, {
    "evaluate_sql_schema_agent": "evaluate_sql_schema_agent", END: END
})
workflow.add_conditional_edges("evaluate_sql_schema_agent", route_to_next, {
    "postgres_schema_agent2": "postgres_schema_agent2", END: END
})
workflow.add_conditional_edges("postgres_schema_agent2", route_to_next, {
    "trigger_generation_agent": "trigger_generation_agent", END: END
})

# After triggers → stored procedures → views → JSON docs → metadata → test cases
workflow.add_conditional_edges("trigger_generation_agent", route_to_next, {
    "stored_procedures_agent": "stored_procedures_agent",  END: END
})
workflow.add_conditional_edges("stored_procedures_agent", route_to_next, {
    "view_generation_agent": "view_generation_agent", END: END
})
workflow.add_conditional_edges("view_generation_agent", route_to_next, {
    "schema_json_agent": "schema_json_agent", END: END
})
workflow.add_conditional_edges("schema_json_agent", route_to_next, {
    "trigger_list_agent": "trigger_list_agent", END: END
})
workflow.add_conditional_edges("trigger_list_agent", route_to_next, {
    "procedures_doc_agent": "procedures_doc_agent", END: END
})
workflow.add_conditional_edges("procedures_doc_agent", route_to_next, {
    "views_doc_agent": "views_doc_agent", END: END
})
workflow.add_conditional_edges("views_doc_agent", route_to_next, {
    "final_metadata_agent": "final_metadata_agent", END: END
})
workflow.add_conditional_edges("final_metadata_agent", route_to_next, {
    "sql_test_case_agent": "sql_test_case_agent",END: END
})
# Then original test‑case → evaluation → apply DDL → apply triggers → apply procs → apply views → run tests
workflow.add_conditional_edges("sql_test_case_agent", route_to_next, {
    "evaluation_agent": "evaluation_agent", END: END
})
workflow.add_conditional_edges("evaluation_agent", route_to_next, {
    "execute_schema_file": "execute_schema_file", END: END
})
workflow.add_conditional_edges("execute_schema_file", route_to_next, {
    "execute_trigger_file": "execute_trigger_file", END: END
})
workflow.add_conditional_edges("execute_trigger_file", route_to_next, {
    "execute_procedures_file": "execute_procedures_file", END: END
})
workflow.add_conditional_edges("execute_procedures_file", route_to_next, {
    "execute_views_file": "execute_views_file", END: END
})
workflow.add_conditional_edges("execute_views_file", route_to_next, {
    "execute_test_cases": "execute_test_cases", END: END
})

# Final end‑of‑line
workflow.add_edge("execute_test_cases", END)

# Entry point & compile
workflow.set_entry_point("conceptual_design_agent")
app = workflow.compile()

# ------------------------------------------------------------------------------
# Main Workflow Runner
# ------------------------------------------------------------------------------
def run_workflow(input_bdd: str):
    workflow_id = str(uuid.uuid4())
    for d in ["bdd_nodes", "sql_nodes", "trigger_nodes", "test_nodes", "ttl_nodes"]:
        os.makedirs(d, exist_ok=True)
    
    initial_state = {
        "bdd_input": input_bdd,
        "workflow_id": workflow_id,
        "token_usage": {},
        "bdd_finalized": False
    }
    
    result = app.invoke(initial_state)
    
    if "error" in result and result["error"]:
        logger.error(f"Workflow terminated with error: {result['error']}")
        return result
        
    # Print token summary
    total_tokens = sum(result.get("token_usage", {}).values())
    logger.info(f"Total tokens used: {total_tokens}")
    for key, value in result.get("token_usage", {}).items():
        logger.info(f"  {key}: {value} tokens")
        
    # Print execution outputs
    for output_key in ["schema_execution_output", "trigger_execution_output", "test_execution_output"]:
        if output_key in result:
            logger.info(f"\n{output_key.upper()}:\n{result[output_key]}")
            
    return result

if __name__ == "__main__":
    bdd_example = """
    Feature: User login and data integrity
      Scenario: Successful user login and audit logging
        Given the user table exists with proper schema
        When a new user with valid credentials is inserted
        Then the user is added and an audit trigger logs the insertion

      Scenario: Failed insertion due to duplicate email
        Given the user table contains a user with email "user@example.com"
        When another user with the same email is inserted
        Then the insertion fails because of a duplicate key error

      Scenario: Cascade deletion with trigger
        Given the user table is populated
        When a user is deleted
        Then the deletion is propagated to related audit tables
    """
    final_result = run_workflow(bdd_example)



# import ast
# import inspect

# def validate_and_suggest_workflow_nodes(route_func, workflow_nodes, globals_dict):
#     source = inspect.getsource(route_func)
#     tree = ast.parse(source)

#     return_strings = set()

#     class ReturnVisitor(ast.NodeVisitor):
#         def visit_Return(self, node):
#             if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
#                 return_strings.add(node.value.value)
#             elif isinstance(node.value, ast.Str):  # Python < 3.8
#                 return_strings.add(node.value.s)

#     ReturnVisitor().visit(tree)

#     # Drop special END case
#     return_strings.discard("END")
#     defined_nodes = set(workflow_nodes)

#     print("🔍 Validating workflow transitions...\n")

#     missing = return_strings - defined_nodes
#     unused = defined_nodes - return_strings
#     fixed = []

#     if missing:
#         print("❌ Missing workflow nodes (used in route_to_next but not defined):")
#         for m in sorted(missing):
#             print(f"   - {m}")
#         print("\n💡 Suggested fixes (copy-paste into your workflow setup):\n")

#         for m in sorted(missing):
#             func = globals_dict.get(m)
#             if func:
#                 print(f"workflow.add_node('{m}', {m})")
#                 fixed.append(m)
#             else:
#                 print(f"# 👀 No function named '{m}' found — define the function before using it.")
    
#     if unused:
#         print("\n⚠️  Warning: Nodes defined in workflow but never used in route_to_next():")
#         for u in sorted(unused):
#             print(f"   - {u}")

#     if not missing:
#         print("✅ All route targets match defined workflow nodes.")

#     return fixed

# # Call this after defining all workflow nodes
# validate_and_suggest_workflow_nodes(route_to_next, workflow.nodes.keys(), globals())
