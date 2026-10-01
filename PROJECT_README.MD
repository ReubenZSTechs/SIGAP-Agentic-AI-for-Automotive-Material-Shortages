# Khotbah Q&A Application

<a id="top"></a>
A multi-agentic application using Langgraph to facilitate a Khotbah Q&A session. The application consists of multiple agents, each with its own role and expertise in handling different aspects.

<br><br>

<details>
<summary><strong>Table of Contents</strong></summary>

- [Background](#background)
- [Key Features](#key-features)
- [Langgraph Architecture](#langgraph-architecture)
- [Langgraph State](#langgraph-state)
- [LLM Models and Roles](#llm-models-and-roles)
- [Node Tasks](#node-tasks)
- [Tools](#tools)
- [Metrics Used](#metrics-used)
- [Future Work](#future-work)

</details>

---

# Background
Crawling through videos of preaches to find a specific topic or delving deeper regarding a specific topic takes a lot of time, especially if the user is not experienced or an expert in the field of theology. This application serves to act as a Q&A application, which user can ask regarding a topic in question and the application will answer the question.

<div align="right">
  <a href="#top">Back to top ⬆</a>
</div>

---

# Key Features
- **Custom-built Agent Architecture**<br>Featuring langgraph architecture for agent and state management across the entire process
- **State-of-the-art Prompting Methods**<br>Using Chain-of-Thought (CoT) prompting for consistency context and context analysis for better answer
- **Local LLM Hosting**<br>Leveraging Ollama to host local LLMs, such as Mistral, Gemma, and Llama for reasoning and working models
- **Multi LLM Model Architecture**<br>Utilizes multi LLM local models for specific tasks assigned later.
- **Supervised Fine Tuned and Reinforcement Learned Models**<br>Use a hybrid approach for fine-tuning and reinforcement learning to improve the model's performance.



<div align="right">
  <a href="#top">Back to top ⬆</a>
</div>

---

# Langgraph Architecture
The proposed Langgraph Architecture for initial phase is as follows

```text 
                                                                              | (Direct Answer) -->      REASONING      --> |
                                                                              |                                             |
USER INPUT QUERY --> PROMPT REFINER --> RETRIEVAL AND UNDERSTANDING MODULE -->| (Explanation)   --> REASONING MODULE 1  --> | --> GENERATE ANSWER --> EVALUATION --> OUTPUT
                                                                              |                                             |
                                                                              | (Analysis)      --> REASONING MODULE 2  --> |
```

Retrieval and Understanding Phase includes:
```text
| --> Generate Subquestions --> |     | --> Understand Intent --> |
|                               | --> |                           | --> Metadata Filtered Advanced RAG
| -->      Generate CoT     --> |     | --> Generate Metadata --> |
```

Reasoning Module 1 includes:
```text
                   |--> AGENT 1 -->|
                   |               |
GENERATE FACTS --> |--> AGENT 2 -->| --> STORE ANSWERS --> CHECK CORRELATION (CONDITION)
                   |               |
                   |--> AGENT 3 -->|
```

Reasoning Module 2 includes:
```text
                                               |--> AGENT 4 -->|
                                               |               |
PARTITION DOCS --> ORCHESTRATOR ASSIGNMENT --> |--> AGENT 5 -->| --> STORE ANSWERS --> CHECK CORRELATION (CONDITION)
                                               |               |
                                               |--> AGENT 6 -->|
```

Note: 
- Should the metric correlation does not reach a threshold of 90%, then the reasoning phase will restart after fact generation or docs partition.
- Reasoning Module 1 will use a blackboard pattern
- Reasoning Module 2 will use a orchestrator worker pattern

<div align="right">
  <a href="#top">Back to top ⬆</a>
</div>

---

# Langgraph State
The langgraph architecture will update the following state architecture as follows

<table>
    <tr>
        <td>State name</td>
        <td>Datatype</td> 
        <td>Description</td>
    </tr>
    <tr>
        <td>Initial Query</td>
        <td>str</td> 
        <td>User query input</td>
    </tr>
    <tr>
        <td>Refined Query</td>
        <td>str</td> 
        <td>Detailed and corrected version of initial query</td>
    </tr>
    <tr>
        <td>CoT Steps</td>
        <td>List[str]</td> 
        <td>Chain of Thought steps</td>
    </tr>
    <tr>
        <td>Sub Questions</td>
        <td>List[str]</td> 
        <td>List of subquestions expanded from original query</td>
    </tr>
    <tr>
        <td>Entity Metadata</td>
        <td>List[str]</td> 
        <td>List all entity related to the original query</td>
    </tr>
    <tr>
        <td>Retrieved Docs</td>
        <td>List[str]</td> 
        <td>Retrieved documents from RAG</td>
    </tr>
    <tr>
        <td>Context</td>
        <td>str</td> 
        <td>Combined context from RAG</td>
    </tr>
    <tr>
        <td>Intent</td>
        <td>str</td> 
        <td>Determines the intent type of the query</td>
    </tr>
    <tr>
        <td>Point of Facts</td>
        <td>List[Dict[str, str]]</td> 
        <td>Fact points from context based on reasoning step</td>
    </tr>
    <tr>
        <td>Reason</td>
        <td>str</td> 
        <td>Containes the reasoning step for direct answer method</td>
    </tr>
    <tr>
        <td>Agent 1 Answer</td>
        <td>str</td> 
        <td>Contains the answer for agent 1</td>
    </tr>
    <tr>
        <td>Agent 2 Answer</td>
        <td>str</td> 
        <td>Contains the answer for agent 2</td>
    </tr>
    <tr>
        <td>Agent 3 Answer</td>
        <td>str</td> 
        <td>Contains the answer for agent 3</td>
    </tr>
    <tr>
        <td>Agent 4 Answer</td>
        <td>str</td> 
        <td>Contains the answer for agent 4</td>
    </tr>
    <tr>
        <td>Agent 5 Answer</td>
        <td>str</td> 
        <td>Contains the answer for agent 5</td>
    </tr>
    <tr>
        <td>Agent 6 Answer</td>
        <td>str</td> 
        <td>Contains the answer for agent 6</td>
    </tr>
    <tr>
        <td>Correlation Argument</td>
        <td>float</td> 
        <td>How does each arguments correlate to one another</td>
    </tr>
    <tr>
        <td>Answer Cache</td>
        <td>List[dict[str, list]]</td> 
        <td>Contains all answers per round for each agents</td>
    </tr>
    <tr>
        <td>Answer</td>
        <td>str</td> 
        <td>Final answer after debating</td>
    </tr>
    <tr>
        <td>Metrics</td>
        <td>Dict[str, float]</td> 
        <td>Metrics reference for evaluation</td>
    </tr>
</table>


<div align="right">
  <a href="#top">Back to top ⬆</a>
</div>

---


# Node Tasks
Each node, starting from `Understanding Phase` up to the `Evaluation Phase` will be limited to the scope of the defined tasks, but not limit to as follows.

<table>
    <tr>
        <td><b>Node</b></td>
        <td><b>Model</b></td>
        <td><b>Reason</b></td>
    </tr>
    <tr>
        <td>Prompt Refiner</td>
        <td>Worker 1</td>
        <td>Prompt will not contain any spelling errors or any grammatical errors</td>
    </tr>
    <tr>
        <td>Generate Sub-Questions</td>
        <td>Worker 2</td>
        <td>Guide the data retrieval RAG to extract full context data</td>
    </tr>
    <tr>
        <td>CoT Steps Generation</td>
        <td>Worker 3</td>
        <td>Based on the user initial query, CoT will help guide the model's thinking</td>
    </tr>
    <tr>
        <td>Intent Generation</td>
        <td>Worker 4</td>
        <td>Based on the query and sub questions, determine the intent of the query</td>
    </tr>
    <tr>
        <td>Analyze Entity</td>
        <td>Worker 5</td>
        <td>Guide the data retrieval RAG for guided-retrieval for entity filter</td>
    </tr>
    <tr>
        <td>Data Retrieval Node</td>
        <td>Advanced RAG</td>
        <td>Does entity filtering and data extraction</td>
    </tr>
    <tr>
        <td>Build context node</td>
        <td>Function</td>
        <td>Converts all docs into one whole context block</td>
    </tr>
    <tr>
        <td>Reasoning</td>
        <td>reasoner</td>
        <td>Reasons the query and output the reasoning given context</td>
    </tr>
    <tr>
        <td>Fact Generation</td>
        <td>Worker 6</td>
        <td>Help make the context into facts for compressed input query</td>
    </tr>
    <tr>
        <td>Agent 1</td>
        <td>Model Agent 1</td>
        <td>Come up with an answer to the query based on facts and write them in a blackboard once done</td>
    </tr>
    <tr>
        <td>Agent 2</td>
        <td>Model Agent 2</td>
        <td>Come up with an answer to the query based on facts and write them in a blackboard once done</td>
    </tr>
    <tr>
        <td>Agent 3</td>
        <td>Model Agent 3</td>
        <td>Come up with an answer to the query based on facts and write them in a blackboard once done</td>
    </tr>
    <tr>
        <td>Orchestrator Task Assignment</td>
        <td>Orchestrator</td>
        <td>Assign tasks to agents based on their expertise</td>
    </tr>
    <tr>
        <td>Agent 4</td>
        <td>Model Agent 4</td>
        <td>Come up with an answer based on the query</td>
    </tr>
    <tr>
        <td>Agent 5</td>
        <td>Model Agent 5</td>
        <td>Come up with an answer based on the query</td>
    </tr>
    <tr>
        <td>Agent 6</td>
        <td>Model Agent 6</td>
        <td>Come up with an answer based on the query</td>
    </tr>
        <tr>
        <td>Store answers</td>
        <td>Function</td>
        <td>Compile all arguments and store them for future reference</td>
    </tr>
        <tr>
        <td>Correlation Checker</td>
        <td>Evaluator</td>
        <td>For the following arguments, see if they correlate one another</td>
    </tr>
        <tr>
        <td>Answer Generation</td>
        <td>Worker 7</td>
        <td>Provided the user context, sub-questions, debating arguments, generate the final answer</td>
    </tr>
        <tr>
        <td>Evalution</td>
        <td>Evalutor</td>
        <td>Measure the metrics</td>
    </tr>
    <tr>
        <td>Print State</td>
        <td>Function</td>
        <td>Print the state in its entirerity</td>
    </tr>
</table>


<div align="right">
  <a href="#top">Back to top ⬆</a>
</div>

---

# LLM Models and Roles
In the initial phase, the proposed roles and LLM models assigned are as follows.

<table>
    <tr>
        <td><b>Role</b></td>
        <td><b>Model</b></td>
        <td><b>Parameter Count</b></td>
        <td><b>Quantized Version</b></td>
    </tr>
    <tr>
        <td>Worker 1*</td>
        <td>Llama3.1-instruct</td>
        <td>8B parameters</td>
        <td>4-bit</td>
    </tr>
    <tr>
        <td>Worker 2*</td>
        <td>Deepseek-r1 Distill Llama 3 - instruct</td>
        <td>8B parameters</td>
        <td>4-bit</td>
    </tr>
    <tr>
        <td>Worker 3*</td>
        <td>Deepseek-r1 Distill Qwen2.5 - instruct</td>
        <td>7B parameters</td>
        <td>4-bit</td>
    </tr>
    <tr>
        <td>Worker 4*</td>
        <td>Gemma4 - Instruct</td>
        <td>4B parameters</td>
        <td>4-bit</td>
    </tr>
    <tr>
        <td>Worker 5*</td>
        <td>Qwen3 - Instruct</td>
        <td>8B parameters</td>
        <td>4-bit</td>
    </tr>
    <tr>
        <td>Worker 6*</td>
        <td>Qwen3 - Instruct</td>
        <td>14B parameters</td>
        <td>4-bit</td>
    </tr>
    <tr>
        <td>Worker 7*</td>
        <td>Gemma3 - Instruct</td>
        <td>12B parameters</td>
        <td>4-bit</td>
    </tr>
    <tr>
        <td>Orchestrator</td>
        <td>Mistral-nemo</td>
        <td>12B parameters</td>
        <td>4-bit</td>
    </tr>
    <tr>
        <td>Agent 1</td>
        <td>Deepseek-r1</td>
        <td>32B parameters</td>
        <td>4-bit</td>
    </tr>
    <tr>
        <td>Agent 2</td>
        <td>Gemma4</td>
        <td>31B parameters</td>
        <td>4-bit</td>
    </tr>
    <tr>
        <td>Agent 3</td>
        <td>Qwen3.6</td>
        <td>35B parameters</td>
        <td>4-bit</td>
    </tr>
    <tr>
        <td>Agent 4</td>
        <td>Deepseek-r1</td>
        <td>32B parameters</td>
        <td>4-bit</td>
    </tr>
    <tr>
        <td>Agent 5</td>
        <td>Gemma4</td>
        <td>31B parameters</td>
        <td>4-bit</td>
    </tr>
    <tr>
        <td>Agent 6</td>
        <td>Qwen3.6</td>
        <td>35B parameters</td>
        <td>4-bit</td>
    </tr>
    <tr>
        <td>Evaluator</td>
        <td>mistral-small</td>
        <td>22B parameters</td>
        <td>4-bit</td>
    </tr>
</table>

Notes: All models highlighted with (*) must go through SFT training (and PPO for future reference)

<div align="right">
  <a href="#top">Back to top ⬆</a>
</div>

---

# Tools
*No tools are given*


<div align="right">
  <a href="#top">Back to top ⬆</a>
</div>

---

# Metrics Used
To evaluate the performance of the model, the `Evaluation` node and other functions will be defined to cover the following metrics.

<table>
    <tr>
        <td><b>Metric</b></td>
        <td><b>What does it measure?</b></td>
    </tr>
    <tr>
        <td>Latency</td>
        <td>Measure the starting time and end time of execution per node</td>
    </tr>
    <tr>
        <td>Coherence</td>
        <td>How coherant are the arguments of the models with the context and fact points</td>
    </tr>
    <tr>
        <td>Faithfulness</td>
        <td>How consistent is the summary to the actual facts</td>
    </tr>
        <tr>
        <td>Relevance</td>
        <td>Is the overall summary relevant to the key points</td>
    </tr>
    <tr>
        <td>Completeness</td>
        <td>How complete is the summary to the key points extracted</td>
    </tr>
    <tr>
        <td>Total Runtime</td>
        <td>Calculates the time it takes to reach from the starting point to the endpoint</td>
    </tr>
    <tr>
        <td>Correlation</td>
        <td>How correlate are the arguments between models</td>
    </tr>
</table>


<div align="right">
  <a href="#top">Back to top ⬆</a>
</div>

---

# Future Work

- [ ] Implement a debater pattern in the `Synthesize` node and/ or the `Self-critic` node
- [ ] Implement a planning agent using the supervisor pattern at the beginning
- [ ] Implement a vector knowledge database to store all reports and generate summary report when needed
- [ ] Upgrade the system to be a chatbot thus implementing a RAG pipeline module

<div align="right">
  <a href="#top">Back to top ⬆</a>
</div>

---