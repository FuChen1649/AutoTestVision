**AI agent 问题**
# 1.大模型怎么并行处理请求：推理阶段权重参数是共享，消耗显存的是单任务的KV catch 也就是是单任务输入的长度产生的权重注意力权重这份是单独，大模型的权重是共享的只参与计算；一个大模型可以支持5-150 的用户活跃度；
# 2.怎么构建短期、长期记忆:短期，上下文，滑动窗口、top3 ;长期QwenEmmbeeding 切块存PGVector 
# 3.怎么构建知识库RAG ： 类似长期记忆，向量化可以用bg3-m3
# 4.怎么管理多步任务agent :
# 5.怎么让模型调用工具
# 6.怎么让模型和外界环境交互，搜索、执行代码、动态选择

**视觉自动化问题**
# 1.怎么判断一条case 是成功还是失败，信任过程该怎么构建: 对啊，愚蠢啊，视觉坐标的代码有了，dom 元素的代码有了；让两套代码同时跑在两台测试机器上，然后让验证agent 检查两套代码期望的一直性不就可以了吗！ 再结合置信度和csae 风险等级 部分人工check 就ok 了啊！
# 2.怎么让agent 在执行过程修复步骤，回到正确位置，修复并继续：虚拟回放就ok了；

Weaver



| #  | 论文                                                                                    | 年份   | arXiv                                                                           |
| -- | ------------------------------------------------------------------------------------- | ---- | ------------------------------------------------------------------------------- |
| 1  | **Attention Is All You Need**                                                         | 2017 | [https://arxiv.org/abs/1706.03762](https://arxiv.org/abs/1706.03762) ([DOI][1]) |
| 2  | **Improving Language Understanding by Generative Pre-Training (GPT-1)**               | 2018 | [https://arxiv.org/abs/1810.04805](https://arxiv.org/abs/1810.04805)            |
| 3  | **BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding**  | 2018 | [https://arxiv.org/abs/1810.04805](https://arxiv.org/abs/1810.04805)            |
| 4  | **Language Models are Unsupervised Multitask Learners (GPT-2)**                       | 2019 | [https://arxiv.org/abs/1905.00064](https://arxiv.org/abs/1905.00064)            |
| 5  | **Language Models are Few-Shot Learners (GPT-3)**                                     | 2020 | [https://arxiv.org/abs/2005.14165](https://arxiv.org/abs/2005.14165)            |
| 6  | **Training language models to follow instructions with human feedback (InstructGPT)** | 2022 | [https://arxiv.org/abs/2203.02155](https://arxiv.org/abs/2203.02155)            |
| 7  | **Chain-of-Thought Prompting Elicits Reasoning in Large Language Models**             | 2022 | [https://arxiv.org/abs/2201.11903](https://arxiv.org/abs/2201.11903)            |
| 8  | **LoRA: Low-Rank Adaptation of Large Language Models**                                | 2021 | [https://arxiv.org/abs/2106.09685](https://arxiv.org/abs/2106.09685)            |
| 9  | **FlashAttention: Fast and Memory-Efficient Exact Attention**                         | 2022 | [https://arxiv.org/abs/2205.14135](https://arxiv.org/abs/2205.14135)            |
| 10 | **LLaMA: Open and Efficient Foundation Language Models**                              | 2023 | [https://arxiv.org/abs/2302.13971](https://arxiv.org/abs/2302.13971)            |

[1]: https://doi.org/10.48550/ARXIV.1706.03762?utm_source=chatgpt.com "[1706.03762] Attention Is All You Need"


| 方向          | 论文                                                                   | arXiv                                                                |
| ----------- | -------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Scaling Law | **Scaling Laws for Neural Language Models**                          | [https://arxiv.org/abs/2001.08361](https://arxiv.org/abs/2001.08361) |
| Chinchilla  | **Training Compute-Optimal Large Language Models**                   | [https://arxiv.org/abs/2203.15556](https://arxiv.org/abs/2203.15556) |
| MoE         | **Switch Transformers**                                              | [https://arxiv.org/abs/2101.03961](https://arxiv.org/abs/2101.03961) |
| RLHF 后续     | **Direct Preference Optimization (DPO)**                             | [https://arxiv.org/abs/2305.18290](https://arxiv.org/abs/2305.18290) |
| RAG         | **Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks** | [https://arxiv.org/abs/2005.11401](https://arxiv.org/abs/2005.11401) |
