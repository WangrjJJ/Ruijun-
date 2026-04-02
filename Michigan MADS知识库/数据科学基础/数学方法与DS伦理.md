---
title: "数学方法与DS伦理"
type: 课程笔记
tags:
  - Michigan
  - MADS
  - 线性代数
  - 优化
  - 伦理
  - 数学基础
status: 已完成
aliases:
  - "Math Methods and DS Ethics"
  - "SIADS 501 502 503 602"
---

# 数学方法与DS伦理

> [!abstract] 概述
> 本笔记整合了MADS数学基础与数据科学伦理课程的核心知识。涵盖线性代数（特征值分解、SVD降维）、梯度下降优化、信息论（熵与互信息），以及AI伦理框架（公平性、偏差、问责）。这些是数据科学家的"底层操作系统"。

## 覆盖课程

| 课程编号 | 课程名称 | 核心主题 |
|---------|---------|---------|
| S501 | Being a Data Scientist | DS身份、宣言、协作 |
| S502 | Math Methods for DS | 线性代数基础、概率 |
| S503 | Data Science Ethics | 伦理框架、偏差、公平 |
| S602 | Math Methods II | SVD、梯度下降、马尔科夫链、信息论 |

## 核心知识一：线性代数基础

### 正交矩阵与可逆矩阵

==正交矩阵==满足 $Q^TQ = QQ^T = I$，行列式 $\det(Q) = \pm 1$。可逆矩阵要求 $\det(A) \neq 0$。

```python
def is_orthogonal(m): return np.linalg.det(m) in [1, -1]
def is_invertible(m): return np.linalg.det(m) != 0
```

### 对称矩阵与正定性

==对称矩阵==满足 $A = A^T$。正定性通过特征值判定：

| 类型 | 条件 |
|-----|------|
| 正定 (Positive Definite) | 所有特征值 $\lambda_i > 0$ |
| 半正定 (Positive Semi-definite) | 所有 $\lambda_i \geq 0$，至少一个为0 |
| 不定 (Indefinite) | 存在 $\lambda_i < 0$ |

> [!tip] 判定正定性的Python模式
> `np.all(np.linalg.eigvals(m) > 0)` 判断正定，`np.all(eigvals >= 0)` 判断半正定。在优化中，Hessian矩阵正定意味着该驻点为局部极小值。

### 特征值分解

矩阵 $A$ 可分解为 $A = S \Lambda S^{-1}$，其中 $\Lambda$ 为特征值对角矩阵，$S$ 为特征向量矩阵。

==矩阵幂的快速计算==：$A^k = S \Lambda^k S^{-1}$，特征值幂次 $\lambda_i^k$ 即可。

```python
def powers_of_matrix(s, a, s_inv, power):
    m = s @ a @ s_inv
    a_power = np.diag(np.diag(a) ** power)
    return s @ a_power @ s_inv
```

## 核心知识二：奇异值分解 (SVD)

SVD将任意 $m \times n$ 矩阵分解为：

$$A = U \Sigma V^T$$

其中 $U$ 为左奇异向量（$m \times m$ 正交矩阵），$\Sigma$ 为奇异值对角矩阵，$V^T$ 为右奇异向量。

### 截断SVD与图像压缩

保留前 $k$ 个最大奇异值实现降维重建：

$$A_k = U_{:,:k} \cdot \text{diag}(\sigma_{:k}) \cdot V_{:k,:}$$

> [!example] 图像压缩实验 (S602 Assignment 2)
> 对360x520灰度图像执行SVD：
> - $k=360$（完整）：几乎无损
> - $k=50$：仍可辨认，压缩率约86%
> - $k=10$：严重模糊但有轮廓
> 
> 存储量从 $360 \times 520 = 187,200$ 降至 $k(360 + 520 + 1)$。

```python
U, sigma, V = np.linalg.svd(image, full_matrices=False)
recon = np.uint8(U[:,:k] @ np.diag(sigma[:k]) @ V[:k,:])
```

## 核心知识三：梯度下降

### 基本公式

对函数 $f(x)$，迭代更新：

$$x_{t+1} = x_t - \alpha \cdot \nabla f(x_t)$$

其中 $\alpha$ 为==学习率==(step size)。

### 常数步长 vs 衰减步长

| 策略 | 更新规则 | 特点 |
|------|---------|------|
| 常数步长 | $\alpha_t = \alpha_0$ | 简单但可能震荡 |
| 衰减步长 | $\alpha_t = \alpha_0 \cdot \gamma^t$ | 更稳定收敛 |

> [!tip] S602 实验洞察
> 对 $f(x) = 3x^4 - 16x^3 + 18x^2$，驻点为 $x \in \{-1, 1, 1.5\}$。从 $x_0 = -0.8$，步长0.02，5次迭代后 $x \approx 0.039$；从 $x_0 = 3.8$ 则趋向 $x \approx 2.991$。初始点决定收敛方向。

### 二次型的梯度

对 $f(x) = x^T A x$，梯度为：

$$\nabla f(x) = (A + A^T) x$$

当 $A$ 对称时简化为 $\nabla f(x) = 2Ax$。

## 核心知识四：马尔科夫链

状态转移矩阵 $P$ 满足每列概率和为1。经过 $n$ 步后的状态概率：

$$\pi_n = P^n \cdot \pi_0$$

> [!example] 自动售货机问题 (S602)
> 四状态（苏打/薯片/口香糖/无）的转移矩阵，经过10次迭代后概率趋于==稳态分布==，与初始状态无关。这是特征值为1对应特征向量的性质。

```python
def markov_event(transition_matrix, start, n):
    prob = start
    for _ in range(n):
        prob = transition_matrix @ prob
    return np.round(prob, 3)
```

## 核心知识五：信息论基础

### 熵 (Entropy)

衡量随机变量的不确定性：

$$H(X) = -\sum_{i} p(x_i) \log_2 p(x_i)$$

### 互信息 (Mutual Information)

衡量两个变量的共享信息量：

$$I(X;Y) = H(X) + H(Y) - H(X,Y)$$

$I(X;Y) = 0$ 表示 $X$ 和 $Y$ 独立。

## 核心知识六：数据科学伦理框架

### 关键伦理原则

| 原则 | 描述 |
|------|------|
| ==公平性 (Fairness)== | 算法不应对受保护群体产生歧视性影响 |
| ==透明性 (Transparency)== | 决策过程应可解释、可审计 |
| ==问责制 (Accountability)== | 数据产品需有明确的责任主体 |
| 隐私 (Privacy) | 数据收集与使用需尊重个人隐私权 |
| 同意 (Consent) | 数据主体应知情同意数据的用途 |

### 偏差类型

- ==历史偏差==：训练数据反映了历史不平等
- ==代表性偏差==：样本不能代表目标人群
- ==测量偏差==：特征的度量方式对不同群体不公平
- ==聚合偏差==：将异质群体视为同质处理

> [!tip] EU AI Act 视角
> S503课程讨论了欧盟AI法案的风险分级框架：不可接受风险（社会评分系统）、高风险（信用评分、招聘）、有限风险（聊天机器人）、最小风险。

## 方法选择指南

```
需要降维？
  ├── 线性降维 → SVD / PCA
  └── 非线性 → t-SNE / UMAP
需要优化？
  ├── 凸函数 → 梯度下降（保证全局最优）
  └── 非凸函数 → 多起始点 + 衰减学习率
需要建模序列？
  └── 状态转移 → 马尔科夫链
需要量化信息？
  └── 特征选择 → 互信息排序
```

## 工具速查

| 任务 | 函数/方法 |
|------|----------|
| 特征值分解 | `np.linalg.eig(A)` |
| SVD分解 | `np.linalg.svd(A, full_matrices=False)` |
| 行列式 | `np.linalg.det(A)` |
| 矩阵求逆 | `np.linalg.inv(A)` |
| 正定性检验 | `np.all(np.linalg.eigvals(A) > 0)` |
| 图像打开/灰度转换 | `PIL.Image.open().convert('L')` |

## 实战洞察

- SVD中 $k$ 的选择是信息保留与存储效率的权衡，通常保留奇异值能量的95%
- 梯度下降的初始点对非凸函数至关重要，可能收敛到不同的局部极小值
- 马尔科夫链的稳态分布对应转移矩阵特征值1的特征向量
- 数据伦理不是"附加项"，而是贯穿数据科学全流程的设计约束
- 对称矩阵的特征值全部为实数，这在PCA中保证了主成分方向的可解释性

## 相关链接

- [[数据可视化与沟通/可视化设计与数据沟通|可视化设计与数据沟通]]
- [[数据工程与处理/大数据与数据架构|大数据与数据架构]]
- [[工程概率与系统优化]]
- [[数据挖掘与商业分析]]
- [[Michigan MADS知识库 MOC|← 返回MADS知识库]]
