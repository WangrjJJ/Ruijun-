---
title: "网络分析与NLP"
type: 课程笔记
tags:
  - Michigan
  - MADS
  - 网络分析
  - NLP
  - NetworkX
  - 文本分类
  - LIME
status: 已完成
aliases:
  - "Network Analysis and NLP"
  - "SIADS 652 655 680"
---

# 网络分析与NLP

> [!abstract] 概述
> 本笔记整合网络分析、自然语言处理和学习分析三门课程的核心知识。涵盖图论中心性度量（度中心性、介数中心性、PageRank）、社区检测、NetworkX实战模式，以及NLP流水线（TF-IDF、讽刺检测、LIME可解释性）。两个领域的交叉点在于社交网络中的文本分析。

## 覆盖课程

| 课程编号 | 课程名称 | 核心主题 |
|---------|---------|---------|
| S652 | Network Analysis | 中心性、社区检测、链路预测 |
| S655 | Natural Language Processing | 文本分类、TF-IDF、讽刺检测、LIME |
| S680 | Learning Analytics | 教育数据挖掘、合作网络分析 |

## 核心知识一：图论基础与中心性

### 中心性度量对比

| 度量 | 公式/含义 | 识别的节点类型 |
|------|----------|--------------|
| ==度中心性== | $C_D(v) = \frac{\deg(v)}{n-1}$ | 连接最多的"社交达人" |
| ==接近中心性== | $C_C(v) = \frac{n-1}{\sum_{u} d(v,u)}$ | 到所有节点最近的"中心位置" |
| ==介数中心性== | $C_B(v) = \sum_{s \neq v \neq t} \frac{\sigma_{st}(v)}{\sigma_{st}}$ | 控制信息流的"桥梁" |
| ==PageRank== | $PR(v) = \frac{1-\alpha}{n} + \alpha \sum_{u \to v} \frac{PR(u)}{\deg^+(u)}$ | 被重要节点指向的"权威" |

> [!example] 星球大战角色网络 (S652 Assignment 1)
> 110个角色节点，按共同出场建边。分析发现：
> - 度中心性最高：节点17（$C_D = 0.376$）
> - 接近中心性最高：节点4（$C_C = 0.552$）
> - 介数中心性最高：节点4（$C_B = 0.213$）
> - PageRank Top3（$\alpha=0.9$）：节点17, 4, 21（三者两两相连）
> 
> ==核心洞察==：不同中心性度量高度重叠，因为核心角色在多个维度上都处于中心位置。

### Hub与Authority (HITS算法)

- ==Hub==：指向许多权威节点的节点（好的"目录页"）
- ==Authority==：被许多Hub指向的节点（好的"内容页"）

> [!tip] 无向图中Hub = Authority
> 在无向图中，Hub分数和Authority分数相同，因为"指向"和"被指向"没有区别。S652的星球大战网络即验证了这一点：Top5 Hub和Top5 Authority完全一致。

```python
hub_scores, authority_scores = nx.hits(G)
top5_hub = sorted(hub.items(), key=lambda x: -x[1])[:5]
```

### 聚类系数与传递性

- ==平均聚类系数==：每个节点的邻居间连接比例的平均值
- ==传递性 (Transitivity)==：全网三角形数量占三元组的比例

$$\text{Transitivity} = \frac{3 \times \text{三角形数}}{\text{三元组数}}$$

> [!example] 星球大战网络
> 平均聚类系数 = 0.677（邻居间高度互连），传递性 = 0.349（全局三角形比例较低）。差异说明小群体内部联系紧密但跨群体连接稀疏。

## 核心知识二：网络鲁棒性与节点移除

### 攻击策略对比

从Facebook网络（节点=用户）中依次移除150个节点，比较三种策略对连通分量数量的影响：

| 策略 | 效果 | 原因 |
|------|------|------|
| 随机移除 | 最慢分裂 | 随机节点多为低中心性 |
| 移除最高度中心性 | 中等分裂 | 高度节点连接多但不一定是"桥" |
| ==移除最高介数中心性== | ==最快分裂== | 介数高的节点是连接子群的桥梁 |

```python
for _ in range(150):
    bc = nx.betweenness_centrality(G1)
    target = sorted(bc.items(), key=lambda x: (-x[1], -x[0]))[0][0]
    G1.remove_node(target)
    bet_move.append(nx.number_connected_components(G1))
```

> [!tip] 实际应用
> 网络鲁棒性分析用于：基础设施韧性评估（电网、交通网）、社交网络中关键传播者识别、网络攻防。

## 核心知识三：节点分类预测

### 特征工程 (网络→表格)

将网络的结构信息转化为节点特征用于分类：

```python
df['degree'] = df['node'].apply(lambda x: dict(G.degree())[x])
df['deg_centrality'] = df['node'].apply(lambda x: nx.degree_centrality(G)[x])
df['closeness'] = df['node'].apply(lambda x: nx.closeness_centrality(G)[x])
df['betweenness'] = df['node'].apply(lambda x: nx.betweenness_centrality(G)[x])
df['pagerank'] = df['node'].apply(lambda x: nx.pagerank(G)[x])
hub, auth = nx.hits(G)
df['hub'] = df['node'].apply(lambda x: hub[x])
```

> [!example] Facebook影响力预测 (S652)
> 用7个网络特征 + RandomForest预测用户是否"有影响力"，F1 > 0.85。最有效特征：degree_centrality, betweenness_centrality, pagerank。

## 核心知识四：NLP文本分类流水线

### TF-IDF特征提取

$$\text{TF-IDF}(t,d) = \text{TF}(t,d) \times \log\frac{N}{\text{DF}(t)}$$

- TF：词在文档中的频率
- IDF：逆文档频率（惩罚高频通用词）

```python
vectorizer = TfidfVectorizer(
    min_df=100,              # 最低文档频率
    stop_words=ENGLISH_STOP_WORDS,
    ngram_range=(1, 2)       # 单词+二元词组
)
X_train = vectorizer.fit_transform(train_df['text'])
```

### 讽刺检测任务

> [!example] Reddit讽刺检测 (S655 Exercise 4.1)
> 数据集：SARC 2.0，257K训练样本（平衡），用 `/s` 标记的讽刺文本。
> 
> | 模型 | 平衡测试F1 | 不平衡测试F1 |
> |------|-----------|-------------|
> | DummyClassifier | 0.503 | 0.050 |
> | LogisticRegression | ==0.605== | 0.094 |
> | RandomForest(50棵,深度15) | 0.435 | 0.123 |
> 
> ==关键发现==：平衡数据上训练的模型在不平衡数据上表现急剧下降。LR在不平衡场景中预测概率偏向>0.5（倾向标记为讽刺），导致大量误报。

### 模型比较

| 特性 | LogisticRegression | RandomForest |
|------|-------------------|-------------|
| 特征类型 | 线性组合 | 特征交互/组合 |
| 训练速度 | 快 | 慢（受树数和深度影响） |
| 可解释性 | 系数直观 | 特征重要性 |
| 平衡F1 | 更高 (0.605) | 较低 (0.435) |

## 核心知识五：LIME可解释性

==LIME== (Local Interpretable Model-agnostic Explanations) 通过局部线性近似解释黑盒模型的单条预测。

### 使用模式

```python
from lime.lime_text import LimeTextExplainer

explainer = LimeTextExplainer(class_names=["not-sarcastic", "sarcastic"])
pipe = make_pipeline(vectorizer, classifier)
explanation = explainer.explain_instance(text, pipe.predict_proba, num_features=10)
explanation.as_pyplot_figure()
```

> [!example] 讽刺检测解释
> 对文本 "Now just get a supercomputer to learn the language..."：
> - LR预测 P(sarcastic)=0.532，RF预测 P(sarcastic)=0.493（两模型不一致）
> - LR关键特征："just"（+0.032，与轻描淡写语气相关）、"assholes"（-0.073，非讽刺信号）
> - "just" 在社会语言学中常用于弱化/轻视语气，与讽刺正相关

### LIME的诊断价值

- 识别模型是否依赖了==虚假相关==（如停用词、标点）
- 帮助发现需要添加/移除的特征
- 对比不同模型的"注意力"差异

## 核心知识六：NLP改进策略

| 策略 | 描述 |
|------|------|
| 重采样 (Resampling) | 欠采样多数类适配不平衡分布 |
| 类别权重 (class_weight) | sklearn的 `class_weight` 参数惩罚不同错误 |
| 讽刺词典 | 构建讽刺高频词特征 |
| 密集表示 | Word2Vec/GloVe替代稀疏TF-IDF |
| 超参优化 | 增加RF树数、允许更深的树 |

## 方法选择指南

```
网络分析任务：
  ├── 找核心节点 → degree_centrality + PageRank
  ├── 找桥梁节点 → betweenness_centrality
  ├── 预测节点标签 → 网络特征 + RandomForest
  └── 网络韧性分析 → 介数攻击模拟

NLP任务：
  ├── 文本分类基线 → TF-IDF + LogisticRegression
  ├── 需要特征交互 → TF-IDF + RandomForest
  ├── 模型诊断 → LIME解释
  └── 不平衡数据 → 重采样 / class_weight调整
```

## 工具速查

| 任务 | 函数/方法 |
|------|----------|
| 读取边列表 | `nx.read_edgelist(file, nodetype=int)` |
| 度中心性 | `nx.degree_centrality(G)` |
| 介数中心性 | `nx.betweenness_centrality(G)` |
| 接近中心性 | `nx.closeness_centrality(G)` |
| PageRank | `nx.pagerank(G, alpha=0.9)` |
| HITS | `nx.hits(G)` |
| 连通分量数 | `nx.number_connected_components(G)` |
| 聚类系数 | `nx.average_clustering(G)` |
| TF-IDF向量化 | `TfidfVectorizer(min_df, ngram_range)` |
| LIME文本解释 | `LimeTextExplainer().explain_instance()` |
| 模型流水线 | `make_pipeline(vectorizer, classifier)` |

## 实战洞察

- 介数中心性计算复杂度为 $O(VE)$，大规模网络上非常慢，考虑近似算法或采样
- 节点移除实验中需 `copy.deepcopy(G)` 保护原始图，因为 `remove_node` 是原地操作
- 讽刺检测F1仅0.6，说明==社会语言信号极难从纯文本中捕获==，需要上下文、语调等多模态信息
- LIME对同一文本的不同模型可能给出截然不同的解释，这本身就是有价值的诊断信息
- 在不平衡测试集上，F1比Accuracy更有意义（Accuracy可通过全预测多数类获得高分）
- NetworkX适合中小规模网络（<100K节点），更大规模需graph-tool或Spark GraphX
- 网络特征（中心性指标）是强大的特征工程手段，可以补充传统表格特征

## 相关链接

- [[数据科学基础/数学方法与DS伦理|数学方法与DS伦理]]
- [[数据可视化与沟通/可视化设计与数据沟通|可视化设计与数据沟通]]
- [[高级分析与应用/毕业项目与实践|毕业项目与实践]]
- [[数据挖掘与商业分析]]
- [[区块链与新技术]]
- [[Michigan MADS知识库 MOC|← 返回MADS知识库]]
