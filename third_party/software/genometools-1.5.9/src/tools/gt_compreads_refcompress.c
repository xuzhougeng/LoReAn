/*
  Copyright (c) 2011 Joachim Bonnet <joachim.bonnet@studium.uni-hamburg.de>
  Copyright (c) 2012 Dirk Willrodt <willrodt@studium.uni-hamburg.de>
  Copyright (c) 2012 Center for Bioinformatics, University of Hamburg

  Permission to use, copy, modify, and distribute this software for any
  purpose with or without fee is hereby granted, provided that the above
  copyright notice and this permission notice appear in all copies.

  THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
  WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
  MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
  ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
  WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
  ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
  OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
*/

#include <string.h>

#include "core/alphabet_api.h"
#include "core/basename_api.h"
#include "core/encseq_api.h"
#include "core/fa.h"
#include "core/fileutils_api.h"
#include "core/ma.h"
#include "core/mathsupport.h"
#include "core/range_api.h"
#include "core/showtime.h"
#include "core/splitter_api.h"
#include "core/undef_api.h"
#include "core/unused_api.h"
#include "core/xansi_api.h"
#include "extended/rcr.h"
#include "tools/gt_compreads_refcompress.h"

typedef struct {
  bool verbose,
       vquals,
       mquals,
       quals,
       ureads,
       descs;
  GtStr *name,
        *ref,
        *align;
  GtUword srate;
  GtRange qrng;
} GtCsrRcrEncodeArguments;

static void* gt_compreads_refcompress_arguments_new(void)
{
  GtCsrRcrEncodeArguments *arguments = gt_calloc((size_t) 1, sizeof *arguments);
  arguments->name = gt_str_new();
  arguments->ref = gt_str_new();
  arguments->align = gt_str_new();
  arguments->qrng.start = GT_UNDEF_UWORD;
  arguments->qrng.end = GT_UNDEF_UWORD;

  return arguments;
}

static void gt_compreads_refcompress_arguments_delete(void *tool_arguments)
{
  GtCsrRcrEncodeArguments *arguments = tool_arguments;
  if (!arguments) return;
  gt_str_delete(arguments->name);
  gt_str_delete(arguments->ref);
  gt_str_delete(arguments->align);
  gt_free(arguments);
}

static GtOptionParser*
gt_compreads_refcompress_option_parser_new(void *tool_arguments)
{
  GtCsrRcrEncodeArguments *arguments = tool_arguments;
  GtOptionParser *op;
  GtOption *option,
           *option1;
  gt_assert(arguments);

  /* init */
  op = gt_option_parser_new("[option ...] (-bam file -ref file)",
                         "Generates compact encoding for fastq data using"
                         " Reference Compressed Reads (RCR).");

  option = gt_option_new_bool("v", "be verbose",
                              &arguments->verbose, false);
  gt_option_parser_add_option(op, option);

  option = gt_option_new_bool("mquals", "store mapping quality for each read",
                              &arguments->mquals, false);
  gt_option_parser_add_option(op, option);

  option = gt_option_new_bool("quals", "store all quality values for each read,"
                                        " this implies enabling of option"
                                        " \"vquals\"",
                              &arguments->quals, false);

  option1 = gt_option_new_bool("vquals", "store quality values of read"
                               " positions having variations compared to"
                               " reference",
                              &arguments->vquals, false);

  gt_option_exclude(option, option1);

  gt_option_parser_add_option(op, option);
  gt_option_parser_add_option(op, option1);

  option = gt_option_new_bool("descs", "store read name for each read",
                              &arguments->descs, false);
  gt_option_parser_add_option(op, option);

  option = gt_option_new_bool("ureads", "store unmapped reads in a separated"
                              " fastq file (base name will be the value given"
                              " in name and suffix will be"
                              " \" _unmapped.fastq\"",
                              &arguments->ureads, false);
  gt_option_parser_add_option(op, option);

  option = gt_option_new_string("ref", "Index file (generated by the gt encseq"
                                " tool) for reference genome.",
                                arguments->ref, NULL);
  gt_option_is_mandatory(option);
  gt_option_parser_add_option(op, option);

  option = gt_option_new_string("bam", "File containing alignment of reads to"
                                " genome (sorted \".bam\" file).",
                                arguments->align, NULL);
  gt_option_is_mandatory(option);
  gt_option_parser_add_option(op, option);

  option = gt_option_new_string("name", "specify base name for RCR to be"
                                " generated. If not set, base name will be set"
                                " to base name of value given for option"
                                " \"bam\"",
                                arguments->name, NULL);
  gt_option_parser_add_option(op, option);

  gt_option_parser_set_min_max_args(op, 0U, 0U);
  return op;
}

static int gt_compreads_refcompress_runner(GT_UNUSED int argc,
                                    GT_UNUSED const char **argv,
                                    GT_UNUSED int parsed_args,
                                    void *tool_arguments, GtError *err)
{
  GtCsrRcrEncodeArguments *arguments = tool_arguments;
  int had_err = 0;
  GtTimer *timer = NULL;
  GtEncseq *encseq = NULL;
  GtRcrEncoder *rcre = NULL;
  GtEncseqLoader *el = NULL;
  GtSplitter *splitter = NULL;
  GtStr *buffer;
  GtUword i;
  gt_error_check(err);
  gt_assert(arguments);
  if (gt_showtime_enabled()) {
    timer = gt_timer_new_with_progress_description("start");
    gt_timer_start(timer);
    gt_assert(timer);
  }
  if (!had_err) {
    if (timer != NULL)
      gt_timer_show_progress(timer, "encoding", stdout);

    if (gt_str_length(arguments->name) == 0) {
      splitter = gt_splitter_new();
      buffer = gt_str_clone(arguments->align);
      gt_splitter_split(splitter, gt_str_get(buffer), gt_str_length(buffer),
                        '.');
      for (i = 0; i < gt_splitter_size(splitter) - 1; i++) {
        gt_str_append_cstr(arguments->name,
                           gt_splitter_get_token(splitter, i));
        if (i < gt_splitter_size(splitter) - 2)
          gt_str_append_char(arguments->name, '.');
      }
      gt_splitter_delete(splitter);
      gt_str_delete(buffer);
    }
    el = gt_encseq_loader_new();
    gt_encseq_loader_enable_autosupport(el);
    gt_encseq_loader_require_description_support(el);
    encseq = gt_encseq_loader_load(el, gt_str_get(arguments->ref), err);
    gt_encseq_loader_delete(el);
    if (!encseq) {
      gt_error_set(err, "could not load GtEncseq %s",
                   gt_str_get(arguments->ref));
      had_err = -1;
    }

    if (!had_err) {
      if (!gt_alphabet_is_dna(gt_encseq_alphabet(encseq))) {
        gt_error_set(err, "alphabet in %s has to be DNA",
                     gt_str_get(arguments->ref));
        had_err = -1;
      }
      if (!had_err) {

        rcre = gt_rcr_encoder_new(encseq, gt_str_get(arguments->align),
                                  arguments->vquals, arguments->mquals,
                                  arguments->quals, arguments->ureads,
                                  arguments->descs, timer, err);
        if (!rcre)
          had_err = -1;
        else {
          if (arguments->verbose)
            gt_rcr_encoder_enable_verbosity(rcre);
          had_err = gt_rcr_encoder_encode(rcre, gt_str_get(arguments->name),
                                          timer, err);
        }
        gt_rcr_encoder_delete(rcre);
      }
    }
    gt_encseq_delete(encseq);
  }
  if (timer != NULL) {
    gt_timer_show_progress_final(timer, stdout);
    gt_timer_delete(timer);
  }
  return had_err;
}

GtTool* gt_compreads_refcompress(void)
{
  return gt_tool_new(gt_compreads_refcompress_arguments_new,
                  gt_compreads_refcompress_arguments_delete,
                  gt_compreads_refcompress_option_parser_new,
                  NULL,
                  gt_compreads_refcompress_runner);
}