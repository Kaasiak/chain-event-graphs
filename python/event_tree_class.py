from collections import defaultdict

from IPython.core.display import display
import scipy.special as special
import seaborn as sns
from operator import add
import pydotplus as ptp
from IPython.display import Image
import random
import itertools
import time
import functools
import datetime
import networkx as nx
import numpy as np

class ceg(object):
	def __init__(self, params):
		self.dataframe = params.get('dataframe')
		self.variables = list(self.dataframe.columns)

		#manually added sampling zeros paths
		self.sampling_zero_paths = params.get('sampling_zero_paths')

		self.paths = defaultdict(int) #dict entry gives the path counts
		self._dummy_paths = defaultdict(int)
		self.nodes = self._nodes() #includes leaves
		self.root = self._nodes()[0]

		#a dict with keys as ((path of edge labels, final edge on path)) 
		#and entry as edge count for the path
		self.edge_information = defaultdict() 

		self.edge_counts = self._edge_counts()
		self.edge_labels = self._edge_labels_creation()

		#each edge is a tuple of (emanating vertex, terminating vertex)
		self.edges = self._edge_creation() 
		self.emanating_nodes = self._emanating_nodes()
		self.terminating_nodes = self._terminating_nodes()

		self.leaves = self._get_leaves()
		self.situations = self._get_situations()

		#list of lists. Each list gives the edge counts of the edges coming
		# from a particular vertex (indices matched with self.situations)
		self.edge_countset = self._edge_countset()

		#used in the AHC method to store 
		#- the list of situations merged into a single stage
		#- the mean posterior conditional probabilities along the edges emanating from each situation
		self._merged_situations = None
		self._mean_posterior_conditional_probabilities = None

		#list of colours for stages/positions as (situation/position, colour)
		self._stage_colours = None 
		self._position_colours = None 
		self._position_colours_optimal = None #with optimal stopping time 

		#shortest distance from a situation to a leaf in the event tree
		self.shortest_path = self._shortest_path()

	def _counts_for_unique_path_counts(self):
		'''adding path dict entries for each path, including the sampling zero paths if any.
		Each path is an ordered sequence of edge labels starting from the root.
		The keys in the dict are ordered alphabetically.
		Also calls the method self.sampling zeros to ensure manually added path format is correct.
		Added functionality to remove NaN/null edge labels assuming they are structural zeroes'''

		self._dummy_paths = defaultdict(int)
		for variable_number in range(0, len(self.variables)):
			dataframe_upto_variable = self.dataframe.loc[:, self.variables[0:variable_number+1]]
			for row in dataframe_upto_variable.itertuples():
				row = row[1:]
				new_row = [edge_label for edge_label in row if edge_label != np.nan and
				str(edge_label) != 'NaN' and str(edge_label) != 'nan' and edge_label != '']
				new_row = tuple(new_row)

				#checking if the last edge label in row was nan. That would result in double counting
				#nan must be identified as string
				if  (row[-1] != np.nan and str(row[-1]) != 'NaN' and str(row[-1]) != 'nan' and row[-1] != ''):
					self._dummy_paths[new_row] += 1

		if self.sampling_zero_paths != None:
			self.sampling_zeros(self.sampling_zero_paths)	

		depth = len(max(list(self._dummy_paths.keys()), key=len))
		keys_of_list = list(self._dummy_paths.keys())
		sorted_keys = []
		for deep in range(0,depth+1):
		    unsorted_mini_list = [key for key in keys_of_list if len(key) == deep]
		    sorted_keys = sorted_keys + sorted(unsorted_mini_list)

		for key in sorted_keys:
			self.paths[key] = self._dummy_paths[key]

		return self.paths

	def sampling_zeros(self, paths):
		'''The sampling zero paths must be tuples in a list. Each tuple is a sampling zero path
		that needs to be added. If multiple edges along a path need to be added, they must be 
		added in order. i.e. path[:-1] should already be a key in self.paths 
		Eg suppose edge 'eat' already exists as an edge emanating from the root. To add paths 
		('eat', 'sleep'), ('eat', 'sleep', 'repeat'), the sampling zero parameter should be added as:
		et = event_tree({'dataframe': df, 'sampling_zero_paths': [('eat', 'sleep',),('eat', 'sleep','repeat',)]})
		'''	
		for path in paths:
			if (path[:-1] in list(self._dummy_paths.keys())) or len(path) == 1:
				self._dummy_paths[path] = 0
			else:
				raise ValueError("The path up to it's last edge should be added first. Ensure the tuple ends with a comma.")

	def _number_of_categories_per_variable(self):
		'''list of number of categories/levels for each variable (a column in the df)'''
		categories_of_variable = []
		for variable in self.variables:
			categories_of_variable.append(len(self.dataframe[variable].unique().tolist()))
		return categories_of_variable

	def _nodes(self):
		'''list of all nodes: includes root, situations, leaves'''
		if len(list(self.paths.keys())) == 0:
			self._counts_for_unique_path_counts()
		node_list = ['s0'] #root node 
		vertex_number = 1 
		for path in list(self.paths.keys()):
			node_list.append('s%d' %vertex_number)
			vertex_number += 1
		return node_list

	def _edges_labels_counts(self):
		'''adds entries to the self.edge_information dict (described in __init__)'''
		edge_labels_list = ['root']
		edges_list = []
		for path in list(self.paths.keys()):
			path = list(path)
			edge_labels_list.append(path)
			if path[:-1] in edge_labels_list:
				path_edge_comes_from = edge_labels_list.index(path[:-1])
				edges_list.append([self.nodes[path_edge_comes_from], self.nodes[edge_labels_list.index(path)]])
			else:
				edges_list.append([self.nodes[0], self.nodes[edge_labels_list.index(path)]])
			self.edge_information[((*path,),(*edges_list[-1],))] = self.paths[tuple(path)]
		return self.edge_information

	def _edge_counts(self):
		'''list of counts along edges. Indexed same as self.edges and self.edge_labels'''
		if len(list(self.edge_information.keys())) == 0:
			self._edges_labels_counts()
		return [self.edge_information[x] for x in list(self.edge_information.keys())]

	def _edge_countset(self):
		'''list of lists. Each list contains counts along edges emanating from a specific situation.
		indexed same as self.situations'''
		edge_countset = []
		for node in self.situations:
			edgeset = [edge_pair[1] for edge_pair in self.edges if edge_pair[0] == node]
			edge_countset.append([self.edge_counts[self.terminating_nodes.index(vertex)] for vertex in edgeset])
		return edge_countset

	def _edge_labels_creation(self):
		'''list of edge labels. Indexed same as self.edges and self.edge_counts'''
		if len(list(self.edge_information.keys())) == 0:
			self._edges_labels_counts()
		return [x[0] for x in list(self.edge_information.keys())]

	def _edge_creation(self):
		'''list of edges. Each edge is a tuple of (emanating vertex, terminating vertex) 
		Indexed same as self.edge_labels and self.edge_counts'''
		if len(list(self.edge_information.keys())) == 0:
			self._edges_labels_counts()
		return [edge_info[1] for edge_info in list(self.edge_information.keys())]

	def _get_leaves(self):
		'''list of leaves'''
		return [edge_pair[1] for edge_pair in self.edges if edge_pair[1] not in self.emanating_nodes]

	def _get_situations(self):
		'''list of situations'''
		return [node for node in self.nodes if node not in self.leaves]

	def _emanating_nodes(self): 
		'''list of situations where edges start. Indexed same as self.edges'''
		return [edge_pair[0] for edge_pair in self.edges]

	def _terminating_nodes(self): 
		'''list of situations where edges terminate. Indexed same as self.edges'''
		return [edge_pair[1] for edge_pair in self.edges]

	def rename_nodes(self, new_node_list):
		'''rename all nodes of the ceg'''
		self.nodes = new_node_list
		self.root = new_node_list[0]

		self.edge_information = defaultdict() 

		self.edge_counts = self._edge_counts()
		self.edge_labels = self._edge_labels_creation()

		#each edge is a tuple of (emanating vertex, terminating vertex)
		self.edges = self._edge_creation() 
		self.emanating_nodes = self._emanating_nodes()
		self.terminating_nodes = self._terminating_nodes()

		self.leaves = self._get_leaves()
		self.situations = self._get_situations()

		#list of lists. Each list gives the edge counts of the edges coming
		# from a particular vertex (indices matched with self.situations)
		self.edge_countset = self._edge_countset()

	def default_equivalent_sample_size(self):
		'''default equivalent sample size for the AHC method set as the maximum number of levels
		for a variable (column in the dataframe)'''
		alpha = max(self._number_of_categories_per_variable()) 
		return alpha

	def default_prior(self, equivalent_sample_size):
		'''default prior set for the AHC method using the mass conservation property.
		That is, the equivalent sample size is the phantom sample starting at the root,
		and it is spread equally across all edges along the tree.	
		(see chapter 5 of Collazo, Gorgen & Smith 'Chain Event Graphs', 2018)
		The prior is a list of lists. Each list gives the prior along the edges of a 
		specific situation. Indexed same as self.situations & self.egde_countset'''

		default_prior = [0] *len(self.situations)
		sample_size_at_node = dict()
		sample_size_at_node[self.root] = equivalent_sample_size
		to_assign_nodes = self.situations.copy()
		for node in to_assign_nodes:
			number_of_occurences = self.emanating_nodes.count(node)
			equal_distribution_of_sample = sample_size_at_node[node]/number_of_occurences
			default_prior[self.situations.index(node)] = [equal_distribution_of_sample] *number_of_occurences
			relevant_terminating_nodes = [self.terminating_nodes[self.edges.index(edge_pair)] for edge_pair in self.edges if edge_pair[0] == node]
			for terminating_node in relevant_terminating_nodes:
				sample_size_at_node[terminating_node] = equal_distribution_of_sample
		return default_prior

	def default_hyperstage(self):
		'''default hyperstage for the AHC method. Hyperstage is a list of lists such that two situaions
		can be in the same stage only if there are elements of the same list for some list in the hyperstage.
		The default is to allow all situations with the same number of outgoing edges and the same edge labels 
		to be in a common list. '''
		default_hyperstage = []
		info_of_edges = []
		for node in self.situations:
			edge_indices = [self.edges.index(edge) for edge in self.edges if edge[0]==node]
			edge_labels = [self.edge_labels[x][-1] for x in edge_indices]
			edge_labels.sort()
			info_of_edges.append([self.emanating_nodes.count(node), edge_labels])

		sorted_info = list(a for a,_ in itertools.groupby(info_of_edges))
		for value in sorted_info:
			situations_with_value_edges = []
			for index in range(0, len(self.situations)):
				if info_of_edges[index] == value:
					situations_with_value_edges.append(self.situations[index])
			default_hyperstage = default_hyperstage + [situations_with_value_edges]
		return default_hyperstage

	def default_compact_hyperstage(self):
		'''similar to a default hyperstage except that there is one added condition. Situations can be in the same
		hyperstage only if they additionally satisfy the condition of being at the same distance from some leaf of 
		the event tree'''

		default_hyperstage = []
		info_of_edges = []
		for node in self.situations:
			edge_indices = [self.edges.index(edge) for edge in self.edges if edge[0]==node]
			edge_labels = [self.edge_labels[x][-1] for x in edge_indices]
			edge_labels.sort()
			info_of_edges.append([self.emanating_nodes.count(node), edge_labels])

		sorted_info = list(a for a,_ in itertools.groupby(info_of_edges))
		for value in sorted_info:
			situations_with_value_edges = []
			for index in range(0, len(self.situations)):
				if info_of_edges[index] == value:
					situations_with_value_edges.append(self.situations[index])
			default_hyperstage = default_hyperstage + [situations_with_value_edges]
		compact_hyperstage = []
		for hyperstage in default_hyperstage:
			hyperstage_with_distance = [(node, self.shortest_path[self.situations.index(node)]) for node in hyperstage]
			for length in range(0, max(self.shortest_path)):
				compact_set = [pair[0] for pair in hyperstage_with_distance if pair[1]== length]
				if compact_set != []:
					compact_hyperstage = compact_hyperstage + [compact_set]
		return compact_hyperstage

	def _event_tree_networkx(self):
		'''Writing the event tree as a networkx graph so as to calculate the shortest distance to a leaf'''
		nodes_for_event_tree = [(node, str(node)) for node in self.nodes]
		tree = nx.DiGraph()
		for edge in self.edges:
			tree.add_edge(edge[0], edge[1])
		return tree

	def _shortest_path(self):
		'''calculating shortest distance from each of the situations to a leaf'''
		tree = self._event_tree_networkx()
		shortest_path = []
		for node in self.situations:
			path_distance = []
			for leaf in self.leaves:
				try:
					path_distance.append(nx.shortest_path_length(tree, node, leaf))
				except:
					pass
			shortest_path.append(min(path_distance))
		return shortest_path

	def posterior(self, prior):
		'''calculating the posterior edge counts for the AHC method. The posterior for each edge is
		obtained as the sum of its prior and edge count. Here we do this such that the posterior is a 
		list of lists. Each list gives the posterior along the edges emanating from a specific vertex.
		The indexing is the same as self.edge_countset and self.situations'''
		posterior = []
		for index in range(0, len(prior)):
			posterior.append(list(map(add, prior[index], self.edge_countset[index])))
		return posterior

	def _function1(self, array):
		'''function to calculate log gamma of the sum of an array'''
		return special.gammaln(sum(array))

	def _function2(self, array):
		'''function to calculate log gamma of each element of an array'''
		return sum([special.gammaln(number) for number in array])

	def _loglikehood(self, prior, posterior):
		'''calculating log likelihood given a prior and posterior'''
		prior_contribution = [(self._function1(element) - self._function2(element)) for element in prior]
		posterior_contribution = [(self._function2(element) - self._function1(element)) for element in posterior]
		return (sum(prior_contribution) + sum(posterior_contribution))

	def _bayesfactor(self, prior1, posterior1, prior2, posterior2):
		'''calculates the bayes factor comparing two models which differ in only one stage'''
		new_prior = list(map(add, prior1, prior2))
		new_posterior = list(map(add, posterior1, posterior2))
		return (self._function1(new_prior) - self._function1(new_posterior) + self._function2(new_posterior) - self._function2(new_prior) 
			+ self._function1(posterior1) + self._function1(posterior2) - self._function1(prior1) - self._function1(prior2) 
			+ self._function2(prior1) + self._function2(prior2) - self._function2(posterior1) - self._function2(posterior2))

	def _issubset(self, item, hyperstage):
		'''fucntion to check if two situations belong to the same set in the hyperstage'''
		if any(set(item).issubset(element) for element in hyperstage) == True:
			return 1
		else:
			return 0 

	def _sort_list(self, a_list_of_lists):
		'''function to sort a list of lists to remove repetitions'''
		for index1 in range(0, len(a_list_of_lists)):
			for index2 in range(index1+1, len(a_list_of_lists)):
				array1 = a_list_of_lists[index1]
				array2 = a_list_of_lists[index2]
				if len(set(array1) & set(array2)) != 0:
					a_list_of_lists.append(list(set(array1) | set(array2)))
					a_list_of_lists[index1] = []
					a_list_of_lists[index2] = []
		new_list_of_lists = [list for list in a_list_of_lists if list != []]
		if new_list_of_lists == a_list_of_lists:
			return new_list_of_lists
		else:
			return self._sort_list(new_list_of_lists)

	def AHC_transitions(self, prior = None, hyperstage = None, alpha = None):
		'''Bayesian Agglommerative Hierarchical Clustering algorithm implementation. It returns a list of lists of 
		the situations which have been merged together, the likelihood of the final model and the mean posterior 
		conditional probabilities of the stages.'''
		if alpha is None:
			alpha = self.default_equivalent_sample_size()
		if prior is None:
			prior = self.default_prior(alpha)
		if hyperstage is None:
			hyperstage = self.default_compact_hyperstage()
		prior = prior.copy()
		self._prior = prior.copy()
		hyperstage = hyperstage.copy()
		posterior = self.posterior(prior).copy()
		length = len(prior)
		likelihood = self._loglikehood(prior, posterior)
		posterior_conditional_probabilities = posterior.copy()

		merged_situation_list = []

		bayesfactor_score = 1
		while bayesfactor_score > 0:
			local_merges = []
			local_scores = []

			for situation1 in range(0, length):
				if all(items ==0 for items in posterior[situation1]) == False: #as we will set one of the merged situations/stages as 0 vectors later to retain indices
					model1 = [prior[situation1], posterior[situation1]]
					for situation2 in range(situation1 +1, length):
						if self._issubset([self.situations[situation1], self.situations[situation2]], hyperstage) == 1 and all(items ==0 for items in posterior[situation2]) == False:
							model2 = [prior[situation2], posterior[situation2]]
							local_scores.append(self._bayesfactor(*model1, *model2))
							local_merges.append([situation1,situation2])
			if local_scores != [] and max(local_scores) > 0:
				bayesfactor_score = max(local_scores)
				merged_situation_list.append(local_merges[local_scores.index(bayesfactor_score)])

				make_changes_to = merged_situation_list[-1]

				prior[make_changes_to[0]] = list(map(add, prior[make_changes_to[0]], prior[make_changes_to[1]]))
				posterior[make_changes_to[0]] = list(map(add, posterior[make_changes_to[0]], posterior[make_changes_to[1]]))

				prior[make_changes_to[1]] = [0] *len(prior[make_changes_to[0]])
				posterior[make_changes_to[1]] = [0] *len(prior[make_changes_to[0]])


				posterior_conditional_probabilities[make_changes_to[0]] = posterior[make_changes_to[0]]
				posterior_conditional_probabilities[make_changes_to[1]] = posterior[make_changes_to[0]]

				likelihood += bayesfactor_score
			elif max(local_scores) <= 0:
				bayesfactor_score = 0

		mean_posterior_conditional_probabilities = []
		for array in posterior_conditional_probabilities:
			total = sum(array)
			mean_posterior_conditional_probabilities.append([round(element/total, 3) for element in array])

		list_of_merged_situations = self._sort_list(merged_situation_list)

		merged_situations = []
		for stage in list_of_merged_situations:
			merged_situations.append([self.situations[index] for index in stage])
		self._merged_situations = merged_situations
		# self._only_one_edge()



		self._mean_posterior_conditional_probabilities = mean_posterior_conditional_probabilities
		number_of_stages = len(self._merged_situations)
		stage_colours = self._generate_colours(number_of_stages)
		colours_for_situations = []

		for node in self.nodes:
			stage_logic_values = [(node in stage) for stage in self._merged_situations] 
			if all(value == (False) for value in stage_logic_values):
				colours_for_situations.append((node, 'white'))
			else:
				colour_index = stage_logic_values.index((True))
				colours_for_situations.append((node, stage_colours[colour_index]))
		self._stage_colours = colours_for_situations

		return (merged_situations, likelihood, mean_posterior_conditional_probabilities)

	# 	NEEDS FIXING
	#	def _only_one_edge(self):
	# 	one_edge_situations = []
	# 	for value in self.situations:
	# 		number_of_edges = [node for node in self.emanating_nodes if node == value]
	# 		if len(number_of_edges) == 1:
	# 			one_edge_situations.append(value)
	# 	if one_edge_situations not in self._merged_situations and one_edge_situations != []: # FIX
	# 		self._merged_situations.append(one_edge_situations)



	def timeit(func):
		'''a decorator function to calculate the time taken to run the code'''
		@functools.wraps(func)
		def newfunc(*args, **kwargs):
			startTime = datetime.datetime.now()
			func(*args, **kwargs)
			elapsedTime = datetime.datetime.now() - startTime
			#print('function [{}] finished in {} ms'.format(
			#	func.__name__, int(elapsedTime.microseconds)))
			return elapsedTime
		return newfunc

	#@timeit
	def _ceg_positions_edges_optimal(self):
		'''This function takes the output of the AHC algorithm and identifies the positions i.e. the vertices of the 
		CEG and the edges of the CEG along with their edge labels and edge counts. Here we use the algorithm in our
		paper with the optimal stopping time.
		NOTE: comment out the decorator on the next line when running the code to draw the graph of the CEG.'''
		if self._merged_situations == None:
			raise ValueError("Run AHC transitions first.")
		if self._mean_posterior_conditional_probabilities == None:
			raise ValueError("Run AHC transitions first.")

		ceg_edge_labels = self.edge_labels.copy()
		ceg_edges = self.edges.copy()
		ceg_prior = []
		for sublist in self._prior:
			ceg_prior = ceg_prior + sublist

		ceg_edge_counts = list(map(add, self.edge_counts.copy(), ceg_prior))

		ceg_positions = self.nodes.copy()
		cut_vertices = []

		for edge in self.edges:
			if edge[1] in self.leaves:
				edge_index = ceg_edges.index(edge)
				ceg_edges.pop(edge_index)
				ceg_edge_labels.append(ceg_edge_labels[edge_index])
				ceg_edge_counts.append(ceg_edge_counts[edge_index])
				ceg_edge_labels.pop(edge_index)
				ceg_edge_counts.pop(edge_index)
				ceg_edges.append((edge[0], 'w_inf'))
				cut_vertices.append(edge[0])
		ceg_positions = [node for node in ceg_positions if node not in self.leaves]
		ceg_positions.append('w_inf')
		cut_vertices = list(set(cut_vertices))

		changes_made = 5
		while changes_made != 0:
			cut_stages = []
			changes_made = 0
			while cut_vertices != []:
				for vertex_1 in cut_vertices:
					cut_stage_1 = [vertex_1]
					vertex_1_info = []
					for edge in ceg_edges:
						if edge[0] == vertex_1:
							edge_index = ceg_edges.index(edge)
							vertex_1_info.append((ceg_edge_labels[edge_index][-1], edge[1]))
					vertex_1_info.sort(key = lambda tup: tup[0])
					for vertex_2 in cut_vertices:
						if vertex_1 != vertex_2:
							logic_values = [(vertex_1 in stage, vertex_2 in stage) for stage in self._merged_situations]
							if any(value == (True, True) for value in logic_values):
								vertex_2_info = []
								for edge in ceg_edges:
									if edge[0]== vertex_2:
										edge_index = ceg_edges.index(edge)
										vertex_2_info.append((ceg_edge_labels[edge_index][-1], edge[1]))
								#checking if the terminating nodes and edge labels match
								vertex_2_info.sort(key = lambda tup: tup[0])
								if vertex_1_info == vertex_2_info:
									cut_stage_1.append(vertex_2)
					if len(cut_stage_1) >1:
						changes_made += 1
					cut_stages.append(cut_stage_1)
					for node in cut_stage_1:
						cut_vertices.remove(node)

			#new vertex set
			add_vertices = [x[0] for x in cut_stages]
			remove_vertices = list(itertools.chain(*cut_stages))
			remove_vertices = [node for node in remove_vertices if node not in add_vertices]
			replacement_nodes = []
			for node in remove_vertices:
				replace_with = [x[0] for x in cut_stages if node in x][0]
				replacement_nodes.append(replace_with)
			ceg_positions = [node for node in ceg_positions if node not in remove_vertices]

			#new edge set
			edges_to_remove = []
			edges_to_adapt = []

			for edge_index in range(0, len(ceg_edges)):
				edge = ceg_edges[edge_index]
				label  = ceg_edge_labels[edge_index][-1]
				if edge[0] in remove_vertices:
					replace_index = []
					edges_to_remove.append(edge)
					replace_node = replacement_nodes[remove_vertices.index(edge[0])]
					for index_2 in range(0, len(ceg_edges)):
						replace_edge = ceg_edges[index_2]
						if replace_edge == (replace_node, edge[1]) and ceg_edge_labels[index_2][-1] == label:
							replace_index.append(index_2)
							break
					if replace_index == []:
						raise ValueError("something is wrong")
					ceg_edge_counts[replace_index[0]] += ceg_edge_counts[edge_index]
				elif edge[1] in remove_vertices:
					edges_to_adapt.append(edge)

			for edge in edges_to_remove:
				edge_index = ceg_edges.index(edge)
				ceg_edges.pop(edge_index)
				ceg_edge_labels.pop(edge_index)
				ceg_edge_counts.pop(edge_index)

			for edge in edges_to_adapt:
				edge_index = ceg_edges.index(edge)
				ceg_edges.pop(edge_index)
				replace_node = replacement_nodes[remove_vertices.index(edge[1])]
				ceg_edges.insert(edge_index, (edge[0], replace_node))

			cut_vertices = [edge[0] for edge in ceg_edges if edge[1] in add_vertices]
			cut_vertices = list(set(cut_vertices))

		colours_for_positions = []
		for position in ceg_positions:
			position_colour = [pair for pair in self._stage_colours if pair[0] == position]
			if len(position_colour) == 0:
				colours_for_positions.append((position, 'white'))
			else:
				colours_for_positions.append(position_colour[0])
		self._position_colours_optimal = colours_for_positions

		edges_in_ceg = ceg_edges.copy()
		for node in ceg_positions:
			edge_indices_for_node = []
			for index in range(0, len(edges_in_ceg)):
				if edges_in_ceg[index][0] == node:
					edge_indices_for_node.append(index)

			counts_for_node = []
			for index in edge_indices_for_node:
				counts_for_node.append(ceg_edge_counts[index])
			total = sum(counts_for_node)
			for index in edge_indices_for_node:
				ceg_edge_counts[index] = round(ceg_edge_counts[index]/total, 3)
		return (ceg_positions, ceg_edges, ceg_edge_labels, ceg_edge_counts)

	#@timeit
	def _ceg_positions_edges(self):
		'''This function takes the output of the AHC algorithm and identifies the positions i.e. the vertices of the 
		CEG and the edges of the CEG along with their edge labels and edge counts. Here we use the generalisation of 
		Silander and Leong's algorithm which is also described in our paper in the Experiments section.
		NOTE: comment out the decorator on the next line when running the code to draw the graph of the CEG.'''
		if self._merged_situations == None:
			raise ValueError("Run AHC transitions first.")
		if self._mean_posterior_conditional_probabilities == None:
			raise ValueError("Run AHC transitions first.")

		ceg_edge_labels = self.edge_labels.copy()
		ceg_edges = self.edges.copy()
		ceg_prior = []
		for sublist in self._prior:
			ceg_prior = ceg_prior + sublist

		ceg_edge_counts = list(map(add, self.edge_counts.copy(), ceg_prior))

		ceg_positions = self.nodes.copy()
		cut_vertices = []

		for edge in self.edges:
			if edge[1] in self.leaves:
				edge_index = ceg_edges.index(edge)
				ceg_edges.pop(edge_index)
				ceg_edge_labels.append(ceg_edge_labels[edge_index])
				ceg_edge_counts.append(ceg_edge_counts[edge_index])
				ceg_edge_labels.pop(edge_index)
				ceg_edge_counts.pop(edge_index)
				ceg_edges.append((edge[0], 'w_inf'))
				cut_vertices.append(edge[0])
		ceg_positions = [node for node in ceg_positions if node not in self.leaves]
		ceg_positions.append('w_inf')
		cut_vertices = list(set(cut_vertices))

		while cut_vertices != ['s0']:
			cut_stages = []
			while cut_vertices != []:
				for vertex_1 in cut_vertices: #choosing a vertex in the current V^{-k} set
					cut_stage_1 = [vertex_1]
					vertex_1_info = [] #stores information on all edges emanating from this vertex
					for edge in ceg_edges:
						if edge[0] == vertex_1:
							edge_index = ceg_edges.index(edge)
							vertex_1_info.append((ceg_edge_labels[edge_index][-1], edge[1]))
					vertex_1_info.sort(key = lambda tup: tup[0])
					for vertex_2 in cut_vertices:
						if vertex_1 != vertex_2: #checks if vertices in the same stage
							logic_values = [(vertex_1 in stage, vertex_2 in stage) for stage in self._merged_situations]
							if any(value == (True, True) for value in logic_values):
								vertex_2_info = []
								for edge in ceg_edges:
									if edge[0]== vertex_2:
										edge_index = ceg_edges.index(edge)
										vertex_2_info.append((ceg_edge_labels[edge_index][-1], edge[1]))
								#checking if the terminating nodes and edge labels match
								vertex_2_info.sort(key = lambda tup: tup[0])
								if vertex_1_info == vertex_2_info:
									cut_stage_1.append(vertex_2)
					cut_stages.append(cut_stage_1)
					for node in cut_stage_1:
						cut_vertices.remove(node)
			

			#new vertex set
			add_vertices = [x[0] for x in cut_stages]
			remove_vertices = list(itertools.chain(*cut_stages))
			remove_vertices = [node for node in remove_vertices if node not in add_vertices]
			replacement_nodes = []
			for node in remove_vertices:
				replace_with = [x[0] for x in cut_stages if node in x][0]
				replacement_nodes.append(replace_with)
			ceg_positions = [node for node in ceg_positions if node not in remove_vertices]

			#new edge set
			edges_to_remove = []
			edges_to_adapt = []

			for edge_index in range(0, len(ceg_edges)):
				edge = ceg_edges[edge_index]
				label  = ceg_edge_labels[edge_index][-1]
				if edge[0] in remove_vertices:
					replace_index = []
					edges_to_remove.append(edge)
					replace_node = replacement_nodes[remove_vertices.index(edge[0])]
					for index_2 in range(0, len(ceg_edges)):
						replace_edge = ceg_edges[index_2]
						if replace_edge == (replace_node, edge[1]) and ceg_edge_labels[index_2][-1] == label:
							replace_index.append(index_2)
							break
					if replace_index == []:
						raise ValueError("something is wrong")
					ceg_edge_counts[replace_index[0]] += ceg_edge_counts[edge_index]
				elif edge[1] in remove_vertices:
					edges_to_adapt.append(edge)

			for edge in edges_to_remove:
				edge_index = ceg_edges.index(edge)
				ceg_edges.pop(edge_index)
				ceg_edge_labels.pop(edge_index)
				ceg_edge_counts.pop(edge_index)

			for edge in edges_to_adapt:
				edge_index = ceg_edges.index(edge)
				ceg_edges.pop(edge_index)
				replace_node = replacement_nodes[remove_vertices.index(edge[1])]
				ceg_edges.insert(edge_index, (edge[0], replace_node))

			cut_vertices = [edge[0] for edge in ceg_edges if edge[1] in add_vertices]
			cut_vertices = list(set(cut_vertices))


		colours_for_positions = []
		for position in ceg_positions:
			position_colour = [pair for pair in self._stage_colours if pair[0] == position]
			if len(position_colour) == 0:
				colours_for_positions.append((position, 'white'))
			else:
				colours_for_positions.append(position_colour[0])
		self._position_colours = colours_for_positions

		edges_in_ceg = ceg_edges.copy()
		for node in ceg_positions:
			edge_indices_for_node = []
			for index in range(0, len(edges_in_ceg)):
				if edges_in_ceg[index][0] == node:
					edge_indices_for_node.append(index)

			counts_for_node = []
			for index in edge_indices_for_node:
				counts_for_node.append(ceg_edge_counts[index])
			total = sum(counts_for_node)
			for index in edge_indices_for_node:
				ceg_edge_counts[index] = round(ceg_edge_counts[index]/total, 3)
		return (ceg_positions, ceg_edges, ceg_edge_labels, ceg_edge_counts)

	def ceg_figure_silander(self, filename):
		'''to output the CEG obtained using the generalisation of the Silander and Leong algorithm described in the
		Experiments section of our paper. 
		NOTE: comment out the decorator (@timeit) from the self._ceg_position_edges() function before running 
		this function.
		'''
		ceg_positions, ceg_edges, ceg_edge_labels, ceg_edge_counts = self._ceg_positions_edges() 
		nodes_for_ceg = [(node, str(node)) for node in ceg_positions]
		ceg_graph = ptp.Dot(graph_type = 'digraph', rankdir = 'LR')
		for edge_index in range(0, len(ceg_edges)):
			edge = ceg_edges[edge_index]
			edge_details = str(ceg_edge_labels[edge_index][-1]) + '\n' + str(ceg_edge_counts[edge_index])
			ceg_graph.add_edge(ptp.Edge(edge[0], edge[1], label = edge_details, labelfontcolor="#009933", fontsize="10.0", color="black" ))
		for node in nodes_for_ceg:
			fill_colour = [pair[1] for pair in self._position_colours if pair[0] == node[0]][0]
			ceg_graph.add_node(ptp.Node(name = node[0], label = node[1], style = "filled", fillcolor = fill_colour))
		ceg_graph.write_png(str(filename) + '.png')
		return Image(ceg_graph.create_png())

	def ceg_figure_optimal(self, filename, return_raw = False, display_probs = True, display_pct = False, params = dict()):
		'''to output the CEG obtained using our algorithm described in our paper. 
		NOTE: comment out the decorator (@timeit) from the self._ceg_position_edges() function before running 
		this function.
		'''
		default_params = {
			'ranksep' : 0.5, 
			'fontsize': 10, 
			'shape': "circle", 
			'width': 0.5, 
			'style': "filled",
			'size': 11.7,
			'digit': 1
		}
		param_values = [default_params[k] if k not in params else params[k] for k in default_params.keys()]
		params = dict(zip(default_params.keys(), param_values))
		ceg_positions, ceg_edges, ceg_edge_labels, ceg_edge_counts = self._ceg_positions_edges_optimal() 
		nodes_for_ceg = [(node, str(node)) for node in ceg_positions]
		ceg_graph = ptp.Dot(
			graph_type = 'digraph', 
			rankdir = 'LR', 
			ranksep = params['ranksep'],
			size = params['size']
		)
		for edge_index in range(0, len(ceg_edges)):
			edge = ceg_edges[edge_index]
			if display_probs:
				if display_pct:
					edge_details = str(ceg_edge_labels[edge_index][-1]) + '\n' + str(round(ceg_edge_counts[edge_index] * 100, params['digit'])) + "\\%"
				else:	
					edge_details = str(ceg_edge_labels[edge_index][-1]) + '\n' + str(ceg_edge_counts[edge_index])
			else:
				edge_details = str(ceg_edge_labels[edge_index][-1])
			ceg_graph.add_edge(ptp.Edge(
				edge[0], edge[1], 
				label = edge_details, 
				labelfontcolor="#009933", 
				fontsize="10.0", 
				color="black" 
			))
		for node in nodes_for_ceg:
			fill_colour = [pair[1] for pair in self._position_colours_optimal if pair[0] == node[0]][0]
			ceg_graph.add_node(ptp.Node(
				name = node[0], 
				label = node[1], 
				style = params['style'], 
				width = params['width'], 
				shape = params['shape'], 
				fillcolor = fill_colour,
				fixedsize = True
			))
		if return_raw:
			return ceg_graph
		ceg_graph.write_png(str(filename) + '.png')
		return Image(ceg_graph.create_png())

	def event_tree_figure(self, filename, display_counts = True, return_raw = False, params = dict()):
		'''function to draw the event tree for the process described by the dataset.'''
		default_params = {
			'ranksep' : 0.5, 
			'fontsize': 10, 
			'shape': "circle", 
			'width': 0.5, 
			'size': 11.7,
			'final_node_size': 0.4,
			'display_edge_labels': True
		}
		param_values = [default_params[k] if k not in params else params[k] for k in default_params.keys()]
		params = dict(zip(default_params.keys(), param_values))
		nodes_for_event_tree = [(node, str(node)) for node in self.nodes]
		event_tree_graph = ptp.Dot(
			graph_type = 'digraph', 
			rankdir = 'LR', 
			ranksep = params['ranksep'], 
			size = params['size']
		)
		for edge in self.edges:
			edge_index = self.edges.index(edge)
			if params['display_edge_labels']:
				if display_counts:	
					edge_details = str(self.edge_labels[edge_index][-1])  + '\\n' + str(self.edge_counts[edge_index])
				else:
					edge_details = str(self.edge_labels[edge_index][-1])
			else:
				edge_details = "" 
			event_tree_graph.add_edge(ptp.Edge(
				edge[0], 
				edge[1], 
				label = edge_details, 
				labelfontcolor="#009933", 
				fontsize = params['fontsize'], 
				color="black" 
			))
		for node in nodes_for_event_tree:
			if node[0] in self.leaves:
				event_tree_graph.add_node(ptp.Node(
					name = node[0],
					label = "",
					shape = "circle",
					width = params['final_node_size'], 
					style = "filled", 
					fillcolor = "#666666"
				))
			else:	
				event_tree_graph.add_node(ptp.Node(
					name = node[0], 
					label = node[1], 
					width = params["width"], 
					shape = params["shape"], 
					fixedsize=True
				))
		event_tree_graph.write_png(str(filename) + '.png')
		if return_raw:
			return event_tree_graph
		return Image(event_tree_graph.create_png())

	def _generate_colours(self, number):
		'''generating unique colours for the staged tree and event tree. This function is seeded so that colours are
		the same on multiple runs of the code'''
		pal = sns.color_palette("Set3", number)
		pal = list(pal.as_hex())
		return pal

	def staged_tree_figure(self, filename, display_counts = True, return_raw = False, params = dict()):
		'''function to draw the staged tree for the process described by the dataset.'''
		try:
			self._merged_situations
			self._mean_posterior_conditional_probabilities
			self._stage_colours
		except ValueError:
			print ("First run self.AHC_transitions()")
		else:
			default_params = {'ranksep' : 0.5, 'fontsize': 10, 'shape': "circle", 'width': 0.5, 'style': "filled", 'size': 11.7}
			param_values = [default_params[k] if k not in params else params[k] for k in default_params.keys()]
			params = dict(zip(default_params.keys(), param_values))
			nodes_for_staged_tree = [(node, str(node)) for node in self.nodes]
			staged_tree_graph = ptp.Dot(
				graph_type = 'digraph', 
				rankdir = 'LR', 
				ranksep = params['ranksep'], 
			)
			for edge in self.edges:
				edge_index = self.edges.index(edge)
				if display_counts:	
					edge_details = str(self.edge_labels[edge_index][-1]) + '\n' + str(self.edge_counts[edge_index])
				else:
					edge_details = str(self.edge_labels[edge_index][-1])
				staged_tree_graph.add_edge(ptp.Edge(
					edge[0], 
					edge[1], 
					label = edge_details, 
					labelfontcolor="#009933", 
					fontsize = params['fontsize'], 
					color="black" 
				))
			for node in nodes_for_staged_tree:
				if node[0] in self.leaves:
					staged_tree_graph.add_node(ptp.Node(
						name = node[0],
						label = "",
						shape = "circle",
						width = 0.4, 
						style = "filled", 
						fillcolor = "#666666"
					))
				else:				
					fill_colour = [pair[1] for pair in self._stage_colours if pair[0] == node[0]][0]
					staged_tree_graph.add_node(ptp.Node(
						name = node[0], 
						label = node[1], 
						width = params["width"], 
						shape = params["shape"], 
						fixedsize=True, 
						style = params["style"], 
						fillcolor = fill_colour
					))
			if return_raw:
				return staged_tree_graph
			staged_tree_graph.write_png(str(filename) + '.png')
			return Image(staged_tree_graph.create_png())









	



